"""
Migration to change Chatbot.site_id (UUID) to Chatbot.site (ForeignKey to Site)
with CASCADE delete behavior.

Since Django ForeignKey 'site' creates column 'site_id', we can directly alter
the existing column to be a proper ForeignKey instead of a UUIDField.
"""
from django.db import migrations, models
import django.db.models.deletion


def delete_orphaned_chatbots(apps, schema_editor):
    """Delete chatbots that reference non-existent sites"""
    Chatbot = apps.get_model('chatbot', 'Chatbot')
    Site = apps.get_model('sites', 'Site')
    
    # Get all valid site IDs
    valid_site_ids = set(Site.objects.values_list('id', flat=True))
    
    # Delete chatbots with invalid site_id
    for chatbot in Chatbot.objects.all():
        if chatbot.site_id and chatbot.site_id not in valid_site_ids:
            chatbot.delete()


def remove_indexes_safely(apps, schema_editor):
    """Safely remove old site_id indexes if they exist"""
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            # Try various possible index names
            indexes_to_remove = [
                'chatbots_site_id_5c7c49_idx',
                'chatbot_sit_site_id_5c7f1b_idx',
                'chatbots_site_id_idx',
            ]
            for index_name in indexes_to_remove:
                cursor.execute(f"DROP INDEX IF EXISTS {index_name}")


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0001_initial'),
        ('chatbot', '0107_alter_chatbot_text_color'),
    ]

    operations = [
        # Step 1: Delete orphaned chatbots that reference non-existent sites
        migrations.RunPython(
            delete_orphaned_chatbots,
            reverse_code=migrations.RunPython.noop,
        ),
        
        # Step 2: Safely remove old indexes  
        migrations.RunPython(
            remove_indexes_safely,
            reverse_code=migrations.RunPython.noop,
        ),
        
        # Step 3: Alter the existing site_id field to be a ForeignKey
        # Django's ForeignKey with name 'site' stores in column 'site_id'
        # So we can alter the existing column to become a proper FK
        migrations.AlterField(
            model_name='chatbot',
            name='site_id',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='+',  # Temporary no related name to avoid conflicts
                to='sites.site',
                db_column='site_id',  # Keep the same column name
                help_text='Associated project/site - chatbots are deleted when site is deleted'
            ),
        ),
        
        # Step 4: Rename the field from site_id to site
        migrations.RenameField(
            model_name='chatbot',
            old_name='site_id',
            new_name='site',
        ),
        
        # Step 5: Update the field with proper related_name
        migrations.AlterField(
            model_name='chatbot',
            name='site',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='chatbots',
                to='sites.site',
                help_text='Associated project/site - chatbots are deleted when site is deleted'
            ),
        ),
        
        # Step 6: Add new index for site FK
        migrations.AddIndex(
            model_name='chatbot',
            index=models.Index(fields=['site'], name='chatbots_site_fk_idx'),
        ),
    ]
