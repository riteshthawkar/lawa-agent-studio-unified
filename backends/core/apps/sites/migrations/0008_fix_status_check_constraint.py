from django.db import migrations


class Migration(migrations.Migration):
    """
    Manually update the PostgreSQL check constraint to allow 'indexing' status.
    Django's AlterField doesn't automatically update existing check constraints.
    """

    dependencies = [
        ('sites', '0007_add_indexing_status'),
    ]

    operations = [
        # Drop the old constraint
        migrations.RunSQL(
            sql='ALTER TABLE sites DROP CONSTRAINT IF EXISTS sites_status_check;',
            reverse_sql='ALTER TABLE sites ADD CONSTRAINT sites_status_check CHECK (status IN (\'active\', \'inactive\'));',
        ),
        # Add the new constraint with 'indexing' included
        migrations.RunSQL(
            sql='ALTER TABLE sites ADD CONSTRAINT sites_status_check CHECK (status IN (\'active\', \'inactive\', \'indexing\'));',
            reverse_sql='ALTER TABLE sites DROP CONSTRAINT IF EXISTS sites_status_check;',
        ),
    ]
