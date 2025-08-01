from django.urls import path
from . import views 

urlpatterns = [
    path('franchiseregister/', views.register_franchise, name='register_franchise'),
    path('franchise/reset-password/', views.reset_franchise_password, name='reset_franchise_password'),
    path('franchise/validate-token/', views.validate_reset_token, name='validate_reset_token'),
    path('toggle-franchise-status/<str:franchise_id>/', views.toggle_franchise_status),#employee toggle
    path('getlocations/', views.get_all_franchise_locations, name='get_all_franchise_locations'),#toggle
    path('getactivelocations/', views.get_inactive_franchise_locations, name='get_active_franchise_locations'),#dropdown
    path('get-franchise/', views.get_registered_franchise, name='get_registered_franchise'),
    path('get-file/<str:file_id>/', views.get_file, name='get_file'),
    path('updatestatus/<str:location_id>/', views.update_franchise_status, name='update_franchise_status'),
    path('get-franchise-edit/<str:franchise_id>/', views.get_franchise, name='get_franchise'),
    path('update-franchise/<str:franchise_id>/', views.update_franchise, name='update_franchise'),
    path('getnextfranchiseid/', views.generate_next_franchise_id, name='generate_next_franchise_id'),
    path('savebarcode/', views.save_barcode,name='save_barcode'),
    path('get_all_barcodes/', views.get_all_barcodes, name='get_all_barcodes'),
    path('getfranchise/', views.get_franchises, name='get_franchises'),
    path('stockbarcode/', views.savestockbarcode, name='savestockbarcode'),
    path('update_barcode_status/<str:barcode_id>/', views.update_barcode_status, name='update_barcode_status'),
    
]
