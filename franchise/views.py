# views.py
from django.views.decorators.csrf import csrf_exempt
from rest_framework.parsers import MultiPartParser
from rest_framework.decorators import api_view, parser_classes
from rest_framework.response import Response
from pyauth.auth import HasRolePermission
from rest_framework import status
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view , permission_classes
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from datetime import datetime, timedelta
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.contrib.auth.hashers import make_password
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse, Http404
from django.core.files.base import ContentFile
from pyauth.auth import HasRolePermission
from pymongo import MongoClient
from bson.objectid import ObjectId
import gridfs
import json
import os
import uuid
from bson.json_util import dumps, loads
from dotenv import load_dotenv


from .models import Franchise
from .serializers import FranchiseSerializer
load_dotenv()

@csrf_exempt
@api_view(['POST'])
@permission_classes([HasRolePermission])
@parser_classes([MultiPartParser])
def register_franchise(request):
    data = request.data.copy()

    # Get files from request
    aadhaar_file = request.FILES.get('aadhaar_proof')
    payment_file = request.FILES.get('payment_proof')
    agreement_file = request.FILES.get('agreement_proof')
    franchise_photo_file = request.FILES.get('franchise_photo')
    user_id = request.auth_metadata.get('auth-user-id')
    # MongoDB connection
    mongo_url = os.getenv("GLOBAL_DB_HOST")
    client = MongoClient(mongo_url)
    db = client["franchise"]
    fs = gridfs.GridFS(db)

    try:
        # Save uploaded files in GridFS and update data dict with file IDs
        user_id = request.auth_metadata.get('auth-user-id')
        if aadhaar_file:
            file_id = fs.put(aadhaar_file.read(), filename=aadhaar_file.name, content_type=aadhaar_file.content_type)
            data['aadhaar_file_id'] = str(file_id)

        if payment_file:
            file_id = fs.put(payment_file.read(), filename=payment_file.name, content_type=payment_file.content_type)
            data['payment_file_id'] = str(file_id)

        if agreement_file:
            file_id = fs.put(agreement_file.read(), filename=agreement_file.name, content_type=agreement_file.content_type)
            data['agreement_file_id'] = str(file_id)

        if franchise_photo_file:
            file_id = fs.put(franchise_photo_file.read(), filename=franchise_photo_file.name, content_type=franchise_photo_file.content_type)
            data['franchise_photo_file_id'] = str(file_id)
        data['createdby'] = data.get('createdby', user_id)
        data['lastmodifiedby'] = data.get('lastmodifiedby', user_id)
        # Validate and save Franchise model data
        serializer = FranchiseSerializer(data=data)
        if serializer.is_valid():
            franchise_data = serializer.save()
       
            franchise_id = data.get('franchise_id')
            if not franchise_id:
                return Response({
                    'error': 'Franchise ID is required for registration'
                }, status=status.HTTP_400_BAD_REQUEST)

            dummy_password = str(uuid.uuid4())[:8]
            hashed_password = make_password(dummy_password)
            reset_token = str(uuid.uuid4())

            franchise_user_collection = db["franchise_user"]
            franchise_user_data = {
                "franchise_id": franchise_id,
                "password": hashed_password,
                "reset_password": True,
                "reset_token": reset_token,
                "reset_token_expires": datetime.utcnow() + timedelta(hours=24),
                "created_date": datetime.utcnow(),
                "created_by": user_id,
                "lastmodified_by": user_id,
                "lastmodified_date": datetime.utcnow()
            }

            franchise_user_collection.insert_one(franchise_user_data)

            send_franchise_welcome_email(
                email=data.get('email'),
                franchise_id=franchise_id,
                reset_token=reset_token,
                franchise_name=data.get('franchiser_name', 'Franchise Partner')
            )

            return Response({
                'message': 'Franchise registered successfully. Password reset email sent.',
                'franchise_id': franchise_id
            }, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        return Response({
            'error': f'Registration failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        client.close()



def send_franchise_welcome_email(email, franchise_id, reset_token, franchise_name):
    """Send welcome email with password reset link"""
    try:
        # Create password reset link
        reset_link = f"{os.getenv('FRONTEND_URL', 'test.shinova.in')}/franchise/reset-password?token={reset_token}&franchise_id={franchise_id}"
        
        # Email context
        context = {
            'franchise_name': franchise_name,
            'franchise_id': franchise_id,  # Use franchise_id instead of employee_id
            'reset_link': reset_link,
            'expiry_hours': 24
        }
        
        # Render email template
        html_message = render_to_string('email/franchise_welcome.html', context)
        plain_message = strip_tags(html_message)
        
        # Send email
        send_mail(
            subject='Welcome to Shanmuga Franchise - Set Your Password',
            message=plain_message,
            from_email=os.getenv('EMAIL_FROM', 'noreply@shanmugafranchise.com'),
            recipient_list=[email],
            html_message=html_message,
            fail_silently=False,
        )
        
        print(f"Welcome email sent successfully to {email}")
        
    except Exception as e:
        print(f"Failed to send email to {email}: {str(e)}")

# HTML view for password reset form
@permission_classes([HasRolePermission])
def reset_password_form(request):
    """Display password reset form"""
    token = request.GET.get('token')
    franchise_id = request.GET.get('franchise_id')  # Changed from employee_id
    
    if not token or not franchise_id:
        return render(request, 'email/error.html', {
            'error': 'Invalid reset link. Token and franchise ID are required.'
        })
    
    # Validate token first
    mongo_url = os.getenv("GLOBAL_DB_HOST")
    client = MongoClient(mongo_url)
    db = client["franchise"]
    franchise_user_collection = db["franchise_user"]
    
    try:
        user = franchise_user_collection.find_one({
            "franchise_id": franchise_id,  # Changed from employeeId
            "reset_token": token,
            "reset_token_expires": {"$gt": datetime.utcnow()}
        })
        
        if not user:
            return render(request, 'email/error.html', {
                'error': 'Invalid or expired reset token. Please request a new password reset link.'
            })
        
        context = {
            'token': token,
            'franchise_id': franchise_id,  # Changed from employee_id
            'email': user.get('email', '')
        }
        
        return render(request, 'email/reset_password.html', context)
        
    except Exception as e:
        return render(request, 'email/error.html', {
            'error': f'An error occurred: {str(e)}'
        })
    finally:
        client.close()

# API endpoint for password reset
@csrf_exempt
@permission_classes([HasRolePermission])
def reset_franchise_password(request):
    """Handle password reset for franchise users"""
    if request.method == 'POST':
        token = request.POST.get('token')
        franchise_id = request.POST.get('franchise_id')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if not all([token, franchise_id, new_password, confirm_password]):
            messages.error(request, 'All fields are required')
            return redirect(f'/franchise/reset-password?token={token}&franchise_id={franchise_id}')
        
        if new_password != confirm_password:
            messages.error(request, 'Passwords do not match')
            return redirect(f'/franchise/reset-password?token={token}&franchise_id={franchise_id}')
        
        if len(new_password) < 8:
            messages.error(request, 'Password must be at least 8 characters long')
            return redirect(f'/franchise/reset-password?token={token}&franchise_id={franchise_id}')

        mongo_url = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_url)
        db = client["franchise"]
        user_collection = db["franchise_user"]
        franchise_collection = db["franchise_franchise"]  # ✅ fixed typo

        try:
            user = user_collection.find_one({
                "franchise_id": franchise_id,
                "reset_token": token,
                "reset_token_expires": {"$gt": datetime.utcnow()}
            })

            if not user:
                messages.error(request, 'Invalid or expired reset token')
                return redirect(f'/franchise/reset-password?token={token}&franchise_id={franchise_id}')

            hashed_password = make_password(new_password)

            # ✅ Update user's password
            user_collection.update_one(
                {"_id": user["_id"]},
                {
                    "$set": {
                        "password": hashed_password,
                        "reset_password": False,
                        "lastmodified_date": datetime.utcnow(),
                        "lastmodified_by": franchise_id
                    },
                    "$unset": {
                        "reset_token": "",
                        "reset_token_expires": ""
                    }
                }
            )

            # ✅ Activate the related franchise
            franchise_collection.update_one(
                {"franchise_id": franchise_id},
                {"$set": {"is_active": True}}
            )

            return render(request, 'email/success.html', {
                'message': 'Password updated successfully. Your account is now active.',
                'franchise_id': franchise_id
            })

        except Exception as e:
            messages.error(request, f'Password reset failed: {str(e)}')
            return redirect(f'/franchise/reset-password?token={token}&franchise_id={franchise_id}')
        finally:
            client.close()

    return reset_password_form(request)

@csrf_exempt
@api_view(['GET'])
@permission_classes([HasRolePermission])
def validate_reset_token(request):
    """Validate if reset token is still valid"""
    token = request.GET.get('token')
    franchise_id = request.GET.get('franchise_id')  # Changed from employee_id
    
    if not token or not franchise_id:
        return Response({
            'error': 'Token and franchise ID are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # MongoDB connection
    mongo_url = os.getenv("GLOBAL_DB_HOST")
    client = MongoClient(mongo_url)
    db = client["franchise"]
    franchise_user_collection = db["franchise_user"]
    
    try:
        user = franchise_user_collection.find_one({
            "franchise_id": franchise_id,  # Changed from employeeId
            "reset_token": token,
            "reset_token_expires": {"$gt": datetime.utcnow()}
        })
        
        if user:
            return Response({
                'valid': True,
                'franchise_id': franchise_id  # Changed from employee_id
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'valid': False,
                'error': 'Invalid or expired token'
            }, status=status.HTTP_400_BAD_REQUEST)
            
    except Exception as e:
        return Response({
            'error': f'Validation failed: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        client.close()


@csrf_exempt
@api_view(['GET'])
@permission_classes([HasRolePermission])
def get_registered_franchise(request):
    try:
        franchises = Franchise.objects.all()
        serializer = FranchiseSerializer(franchises, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

    
@api_view(['GET'])
@permission_classes([HasRolePermission])
def get_inactive_franchise_locations(request):
    try:
        mongo_url = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_url)
        db = client["franchise"]

        # Collections
        franchise_collection = db["franchise_franchise"]
        location_collection = db["franchise_location_details"]

        # Step 1: Get all ACTIVE franchise location_ids
        active_franchises = franchise_collection.find({ "is_active": True }, { "location_id": 1 })
        active_location_ids = [item["location_id"] for item in active_franchises if "location_id" in item]

        # Step 2: Find all location documents that are either inactive or belong to inactive franchises
        # Meaning: include records where location_id NOT in active_location_ids
        data = list(location_collection.find({
            "location_id": { "$nin": active_location_ids }
        }))

        json_data = dumps(data, indent=2)
        return HttpResponse(json_data, content_type="application/json")

    except Exception as e:
        return HttpResponse(
            dumps({ "error": str(e) }),
            content_type="application/json",
            status=500
        )

    

#toggle the loctaion true or false
@api_view(['GET'])
@permission_classes([HasRolePermission])
def get_all_franchise_locations(request):
    try:
        mongo_url = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_url)
        db = client["franchise"]
        collection = db["franchise_location_details"]

        data = list(collection.find())

        # Convert _id and datetime properly
        for item in data:
            item["_id"] = str(item["_id"])
            if "created_date" in item:
                item["created_date"] = item["created_date"].isoformat()
            if "lastmodified_date" in item:
                item["lastmodified_date"] = item["lastmodified_date"].isoformat()

        return JsonResponse(data, safe=False)

    except Exception as e:
        return JsonResponse({ "error": str(e) }, status=500)


@csrf_exempt
@api_view(['GET'])
# @permission_classes([HasRolePermission])
def get_file(request, file_id):
    """
    Retrieve file from GridFS by file_id
    """
    try:
        # MongoDB connection
        mongo_url = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_url)
        db = client["franchise"]
        fs = gridfs.GridFS(db)
        
        # Get file from GridFS
        file_obj = fs.get(ObjectId(file_id))
        
        # Create HTTP response with file content
        response = HttpResponse(
            file_obj.read(),
            content_type=file_obj.content_type or 'application/octet-stream'
        )
        
        # Set filename in response header
        response['Content-Disposition'] = f'inline; filename="{file_obj.filename}"'
        
        return response
        
    except gridfs.NoFile:
        return Response({'error': 'File not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PATCH'])
@permission_classes([HasRolePermission])
def update_franchise_status(request, location_id):
    try:
        # Connect to MongoDB
        mongo_url = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_url)
        db = client["franchise"]
        collection = db["franchise_location_details"]
        user_id = request.auth_metadata.get('auth-user-id')
        # Parse the ObjectId
        object_id = ObjectId(location_id)
        
        # Get is_active value from request body
        is_active = request.data.get("is_active")

        # Update the document
        result = collection.update_one(
            {"_id": object_id},
            {
                "$set": {
                    "is_active": is_active,
                    "lastmodified_by": user_id,
                    "lastmodified_date": datetime.utcnow()
                }
            }
        )

        if result.matched_count == 0:
            return JsonResponse({"error": "Franchise location not found."}, status=404)

        return JsonResponse({"message": "Status updated successfully."}, status=200)

    except Exception as e:
        print("Error:", str(e))
        return JsonResponse({"error": "Something went wrong."}, status=500)


@api_view(['PATCH'])
@permission_classes([HasRolePermission])
def toggle_franchise_status(request, franchise_id):
    try:
        mongo_url = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_url)
        db = client["franchise"]
        collection = db["franchise_franchise"]
        user_id = request.auth_metadata.get('auth-user-id')
        franchise = collection.find_one({"franchise_id": franchise_id})
        if not franchise:
            return Response({"error": "franchise not found"}, status=status.HTTP_404_NOT_FOUND)

        # Toggle is_active
        new_status = not franchise.get("is_active", True)

        collection.update_one(
            {"franchise_id": franchise_id},
            {
                "$set": {
                    "is_active": new_status,
                    "lastmodified_by": user_id,
                    "lastmodified_date": datetime.utcnow()
                }
            }
        )


        return Response({"message": "Status updated", "is_active": new_status}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@require_http_methods(["GET"])
@permission_classes([HasRolePermission])
def get_franchise(request, franchise_id):
    """
    Get details of a specific franchise by franchise_id
    """
    try:
        franchise = get_object_or_404(Franchise, franchise_id=franchise_id)
        
        # Convert model instance to dictionary
        franchise_data = {

            'franchise_id': franchise.franchise_id,
            'franchiser_name': franchise.franchise_name,
            'location': franchise.location_id,
            'contact_no': franchise.contact_no,
            'email': franchise.email,
            'alt_number': franchise.alt_number,
            'address': franchise.address,
            'qualification': franchise.qualification,
            'age': franchise.age,
            'gender': franchise.gender,
            'pincode': franchise.pincode,
            'dob': franchise.dob.isoformat() if franchise.dob else None,
            'is_active': franchise.is_active,
            'aadhaar_file_id': franchise.aadhaar_file_id,
            'payment_file_id': franchise.payment_file_id,
            'agreement_file_id': franchise.agreement_file_id,
            'franchise_photo_file_id': franchise.franchise_photo_file_id,
        }
        
        return JsonResponse(franchise_data)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)



# Custom JSON encoder to convert ObjectId → str
class MongoJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        return super().default(obj)

# -----------------------------------------------------------------------------
# PUT/PATCH /update_franchise/<franchise_id>/
# -----------------------------------------------------------------------------
from gridfs import GridFS
@csrf_exempt
@require_http_methods(["POST"])
@permission_classes([HasRolePermission])
def update_franchise(request, franchise_id):
    """
    Update franchise details (in MongoDB) by franchise_id.
    Replaces any ORM/serializer usage with direct pymongo calls.
    """
    try:
        # 1) Connect to MongoDB
        mongo_url = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_url)
        db = client["franchise"]
        collection = db["franchise_franchise"]
        fs = GridFS(db) 

        # 2) First, check that a document with this franchise_id exists
        existing = collection.find_one({"franchise_id": franchise_id})
        print("existing",existing)
        if not existing:
            # If no document, return 404
            raise Http404(f"No franchise found with franchise_id={franchise_id}")

        # 3) Build a dict of fields to set
        update_fields = {}

        # Text fields in request.POST (same names as in Mongo)
        text_keys = [
            "franchiser_name",
            "location",
            "contact_no",
            "email",
            "alt_number",
            "address",
            "qualification",
            "age",
            "gender",
            "pincode",
            "dob",
            # You also had "is_active"
        ]
        for key in text_keys:
            if key in request.POST:
                val = request.POST.get(key)
                if key == "age":
                    try:
                        val = int(val)
                    except ValueError:
                        # Ignore if not a valid int
                        continue
                if key == "dob":
                    # Expecting an ISO date‐string; store as datetime or string
                    try:
                        val = datetime.fromisoformat(val)
                    except Exception:
                        # If it fails, just pass it through as string
                        pass
                update_fields[key] = val

        # Handle the boolean "is_active" explicitly
        if "is_active" in request.POST:
            is_active_str = request.POST.get("is_active").lower()
            update_fields["is_active"] = (is_active_str == "true")

        # 4) Handle any file uploads: generate a UUID, save to default_storage,
        #    then write the new file_id into Mongo under the appropriate field name.
        file_fields_map = {
            "aadhaar_file": "aadhaar_file_id",
            "payment_file": "payment_file_id",
            "agreement_file": "agreement_file_id",
            "franchise_photo": "franchise_photo_file_id",
        }
        for incoming_name, mongo_field in file_fields_map.items():
            if incoming_name in request.FILES:
                uploaded_file = request.FILES[incoming_name]

                # Save file to GridFS
                file_id = fs.put(
                    uploaded_file.read(),
                    filename=uploaded_file.name,
                    content_type=uploaded_file.content_type
                )

                # Convert ObjectId to string before storing
                update_fields[mongo_field] = str(file_id)

        # 5) If there’s anything to update, run the $set
        if update_fields:
            collection.update_one(
                {"franchise_id": franchise_id},
                {"$set": update_fields}
            )

        # 6) Retrieve the freshly updated document
        updated = collection.find_one({"franchise_id": franchise_id})
        if not updated:
            # This should not happen immediately after update_one, but guard anyway
            raise Http404(f"franchise vanished after update: franchise_id={franchise_id}")

        # 7) Convert the Mongo document into a JSON‐serializable dict
        #    (drop _id or convert it to string, etc.)
        #    Optionally convert any datetime fields back to ISO strings.
        result = {}
        for k, v in updated.items():
            if isinstance(v, ObjectId):
                result[k] = str(v)
            elif isinstance(v, datetime):
                result[k] = v.isoformat()
            else:
                result[k] = v

        return JsonResponse(result, encoder=MongoJSONEncoder, safe=False)

    except Http404 as e:
        return JsonResponse({"error": str(e)}, status=404)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@permission_classes([HasRolePermission])
def generate_next_franchise_id(collection):
    last_franchise = Franchise.objects.order_by('-franchise_id').first()
    
    if last_franchise:
        last_id_num = int(last_franchise.franchise_id.replace('SHF', ''))
        next_id_num = last_id_num + 1
    else:
        next_id_num = 1  # start from SHF001 if no data exists

    next_franchise_id = f'SHF{next_id_num:03d}'  # Pads with leading zeros

    return JsonResponse({'franchise_id': next_franchise_id})


from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
import json
from .models import BarcodeRange
from .serializers import BarcodeRangeSerializer


@api_view(['GET'])
@permission_classes([HasRolePermission])
def get_all_barcodes(request):
    barcodes = BarcodeRange.objects.all().order_by('-createdAt')
    serializer = BarcodeRangeSerializer(barcodes, many=True)
    return Response(serializer.data)



from rest_framework.decorators import api_view
from rest_framework.response import Response
from bson import ObjectId
from pymongo import MongoClient
import os

@api_view(['PATCH'])
@permission_classes([HasRolePermission])
def update_barcode_status(request, barcode_id):
    try:
        mongo_url = os.getenv("GLOBAL_DB_HOST")
        client = MongoClient(mongo_url)
        db = client["franchise"]
        collection = db["franchise_barcoderange"]

        # Parse request body
        new_status = request.data.get("is_active")
        if new_status is None:
            return Response({"error": "Missing 'is_active' field"}, status=400)

        # Update the is_active field
        result = collection.update_one(
            {"_id": ObjectId(barcode_id)},
            {"$set": {"is_active": new_status}}
        )

        if result.matched_count == 0:
            return Response({"error": "Document not found"}, status=404)

        return Response({"message": "Status updated successfully"})

    except Exception as e:
        return Response({"error": str(e)}, status=500)
    


from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from .models import BarcodeRange,barcodestock
from .serializers import BarcodeRangeSerializer

@api_view(['POST'])
@permission_classes([HasRolePermission])
def save_barcode(request):
    startbarcode = request.data.get("startbarcode")
    endbarcode = request.data.get("endbarcode")

    # ✅ Validation: Ensure barcodes are strings of digits
    try:
        start = int(startbarcode)
        end = int(endbarcode)
    except (TypeError, ValueError):
        return Response({"message": "Invalid barcode format."}, status=status.HTTP_400_BAD_REQUEST)

    if start > end:
        return Response({"message": "Start barcode cannot be greater than end barcode."}, status=status.HTTP_400_BAD_REQUEST)

    # ✅ Step 1: Ensure barcode range is completely within a stock barcode range
    stock_match = barcodestock.objects.filter(
        startbarcode__lte=startbarcode,
        endbarcode__gte=endbarcode
    ).exists()

    if not stock_match:
        return Response(
            {"message": "Requested barcode range is not available in stock."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ✅ Step 2: Check if the requested range overlaps with existing generated ranges
    overlap = BarcodeRange.objects.filter(
        startbarcode__lte=endbarcode,
        endbarcode__gte=startbarcode
    ).exists()

    if overlap:
        return Response(
            {"message": "Already stored between that range."},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ✅ Step 3: Save
    serializer = BarcodeRangeSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response({'message': 'Barcode range saved successfully.'}, status=status.HTTP_201_CREATED)

    return Response({'message': 'Validation failed.', 'errors': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)




from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .serializers import BarcodestockSerializer

@api_view(['POST'])
@permission_classes([HasRolePermission])
def savestockbarcode(request):
    user_id = request.auth_metadata.get('auth-user-id')

    data = request.data.copy()  # Make the data mutable
    data['createdby'] = user_id  # Set createdby manually

    serializer = BarcodestockSerializer(data=data)
    if serializer.is_valid():
        serializer.save()
        return Response({'message': 'Barcode stock saved successfully'}, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)






from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Franchise
from .serializers import FranchiseSerializer

@api_view(['GET'])
@permission_classes([HasRolePermission])
def get_franchises(request):
    franchises = Franchise.objects.all()
    serializer = FranchiseSerializer(franchises, many=True)
    return Response(serializer.data)



