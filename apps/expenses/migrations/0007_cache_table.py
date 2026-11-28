"""Make the database table of Django's cache, which holds the AI request counters.

Django's ``createcachetable`` makes it; it does nothing when the table is already there. The
table is not removed when going back: it holds only short-lived counters.
"""

from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):
    dependencies = [("expenses", "0006_custom_types")]

    operations = [migrations.RunPython(create_cache_table, migrations.RunPython.noop)]
