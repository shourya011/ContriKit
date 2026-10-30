"""Remove the editor role and convert existing editor accounts to viewers.

Viewer and admin accounts are untouched. Existing editor users keep their
account, password, bookmarks, and profile; only the obsolete role value is
normalized so the removed workflow cannot be selected again.
"""

from django.db import migrations, models


def editors_to_viewers(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(role='editor').update(role='viewer')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(editors_to_viewers, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[('viewer', 'Viewer'), ('admin', 'Admin')],
                default='viewer',
                max_length=10,
            ),
        ),
    ]
