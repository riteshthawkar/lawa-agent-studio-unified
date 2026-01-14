"""
Payment Admin Configuration.
"""

from django.contrib import admin
from apps.payments.models import PaymentEvent, Invoice, CheckoutSession


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ['stripe_event_id', 'event_type', 'organization', 'processed', 'created_at']
    list_filter = ['event_type', 'processed', 'created_at']
    search_fields = ['stripe_event_id', 'organization__name']
    readonly_fields = ['stripe_event_id', 'event_type', 'raw_data', 'processed', 'processed_at', 'error_message', 'created_at']
    ordering = ['-created_at']
    
    def has_add_permission(self, request):
        return False  # Events are created by webhooks only
    
    def has_change_permission(self, request, obj=None):
        return False  # Events should not be modified


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['number', 'organization', 'status', 'total_dollars', 'invoice_date', 'paid_at']
    list_filter = ['status', 'invoice_date']
    search_fields = ['number', 'organization__name', 'stripe_invoice_id']
    readonly_fields = ['stripe_invoice_id', 'stripe_customer_id', 'hosted_invoice_url', 'invoice_pdf']
    ordering = ['-invoice_date']
    
    def total_dollars(self, obj):
        return f"${obj.total_dollars:.2f}"
    total_dollars.short_description = 'Total'


@admin.register(CheckoutSession)
class CheckoutSessionAdmin(admin.ModelAdmin):
    list_display = ['stripe_session_id', 'organization', 'target_plan', 'status', 'created_at', 'completed_at']
    list_filter = ['target_plan', 'status', 'created_at']
    search_fields = ['stripe_session_id', 'organization__name']
    readonly_fields = ['stripe_session_id', 'stripe_price_id', 'completed_at', 'expires_at']
    ordering = ['-created_at']
