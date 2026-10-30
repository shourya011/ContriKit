"""Move Repo state into ``issues`` and add GitHub synchronization fields.

The historical ``repos`` app owned ``Repo`` (table ``repos_repo``) and the
``Issue.repo`` foreign key pointed at it. The model now lives in ``issues`` and
deliberately keeps the original table name, so this migration is data-safe:

* existing repository rows stay in place;
* ``editor_id`` (an editor-only relationship) is removed if it is still
  present in an existing database;
* ``posted_by`` becomes nullable because synchronized issues are authored by
  GitHub, not by a ContribKit editor;
* new sync bookkeeping columns are added on top of the existing table.

Fresh databases get the same shape; the conditional editor removal is a no-op
there because the rewritten initial migration never creates that column.
"""

from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def remove_editor_column(apps, schema_editor):
    """Drop the legacy editor ownership column when upgrading an old database.

    ``Repo`` state no longer contains the field, so the schema editor cannot be
    asked to remove it through a normal ``RemoveField`` operation. Introspect
    the physical table and remove dependent indexes/constraints first, then the
    column. Repository rows and every issue relationship are preserved; only
    the editor-only ownership relationship is removed.

    SQLite, MySQL and PostgreSQL are all handled. Older SQLite versions that
    cannot ``DROP COLUMN`` fall back to the table-rebuild procedure recommended
    by SQLite: create a new table with the surviving columns, copy the rows,
    drop the old table, and rename the new one.
    """
    connection = schema_editor.connection
    table_name = 'repos_repo'
    column_name = 'editor_id'
    vendor = connection.vendor

    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }
        if column_name not in columns:
            return
        constraints = connection.introspection.get_constraints(cursor, table_name)
        surviving = [name for name in columns if name != column_name]

    table = schema_editor.quote_name(table_name)
    column = schema_editor.quote_name(column_name)

    # MySQL/PostgreSQL: a column that is part of a foreign key cannot be
    # dropped until the constraint is gone.
    if vendor != 'sqlite':
        for name, info in constraints.items():
            if column_name not in (info.get('columns') or []):
                continue
            if info.get('foreign_key'):
                quoted = schema_editor.quote_name(name)
                if vendor == 'mysql':
                    schema_editor.execute(f'ALTER TABLE {table} DROP FOREIGN KEY {quoted}')
                else:
                    schema_editor.execute(f'ALTER TABLE {table} DROP CONSTRAINT {quoted}')

    # Indexes that include the column block SQLite's DROP COLUMN and are
    # pointless on the other backends once the constraint is gone.
    for name, info in constraints.items():
        if column_name not in (info.get('columns') or []):
            continue
        if info.get('primary_key') or info.get('foreign_key') and vendor != 'sqlite':
            continue
        quoted = schema_editor.quote_name(name)
        try:
            if vendor == 'mysql':
                schema_editor.execute(f'ALTER TABLE {table} DROP INDEX {quoted}')
            else:
                schema_editor.execute(f'DROP INDEX IF EXISTS {quoted}')
        except Exception:
            # A constraint may have already removed the index implicitly.
            pass

    try:
        schema_editor.execute(f'ALTER TABLE {table} DROP COLUMN {column}')
        return
    except Exception:
        if vendor != 'sqlite':
            raise

    # SQLite < 3.35 fallback: rebuild the table without the editor column.
    quote = schema_editor.quote_name
    with connection.cursor() as cursor:
        cursor.execute(f'PRAGMA table_info({table})')
        table_info = cursor.fetchall()
    if not surviving:
        raise RuntimeError('Refusing to rebuild repos_repo without any columns.')

    def column_sql(info):
        # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
        _, name, col_type, notnull, default, pk = info
        parts = [quote(name)]
        if col_type:
            parts.append(col_type)
        if pk:
            parts.append('PRIMARY KEY')
        if notnull:
            parts.append('NOT NULL')
        if default is not None:
            parts.append(f'DEFAULT {default}')
        return ' '.join(parts)

    tmp_table = quote(f'{table_name}__without_editor')
    definitions = ', '.join(
        column_sql(info) for info in table_info if info[1] in surviving
    )
    schema_editor.execute(f'CREATE TABLE {tmp_table} ({definitions})')
    copied = ', '.join(quote(name) for name in surviving)
    schema_editor.execute(
        f'INSERT INTO {tmp_table} ({copied}) SELECT {copied} FROM {table}'
    )
    schema_editor.execute(f'DROP TABLE {table}')
    schema_editor.execute(f'ALTER TABLE {tmp_table} RENAME TO {table}')


class Migration(migrations.Migration):

    dependencies = [
        ('issues', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='repo',
            name='sync_checkpoint',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='repo',
            name='sync_cursor',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='repo',
            name='sync_mode',
            field=models.CharField(blank=True, default='', max_length=12),
        ),
        migrations.AddField(
            model_name='repo',
            name='sync_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='repo',
            name='last_synced_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='repo',
            name='last_full_sync_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='repo',
            name='last_sync_error',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='issue',
            name='github_id',
            field=models.BigIntegerField(blank=True, db_index=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='issue',
            name='labels',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name='issue',
            name='posted_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='posted_issues',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='issue',
            name='difficulty',
            field=models.CharField(
                choices=[('beginner', 'Beginner'), ('intermediate', 'Intermediate')],
                default='beginner',
                max_length=15,
            ),
        ),
        migrations.AlterField(
            model_name='issue',
            name='estimated_hours',
            field=models.DecimalField(
                decimal_places=1, default=Decimal('2.0'), max_digits=4
            ),
        ),
        migrations.AlterModelOptions(
            name='issue',
            options={'ordering': ('-created_at',)},
        ),
        migrations.RunPython(remove_editor_column, migrations.RunPython.noop),
    ]
