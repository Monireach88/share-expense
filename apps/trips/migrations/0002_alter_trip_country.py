import django_countries.fields
from django.db import migrations
from django_countries import countries


def names_to_codes(apps, schema_editor):
    # The field was free text ("Vietnam"); it now stores the ISO code ("VN").
    # A name with no match is cleared, because it cannot fit in 2 characters.
    Trip = apps.get_model("trips", "Trip")
    for trip in Trip.objects.exclude(country=""):
        trip.country = countries.by_name(trip.country.strip(), insensitive=True) or ""
        trip.save(update_fields=["country"])


def codes_to_names(apps, schema_editor):
    Trip = apps.get_model("trips", "Trip")
    for trip in Trip.objects.exclude(country=""):
        trip.country = countries.name(trip.country)
        trip.save(update_fields=["country"])


class Migration(migrations.Migration):
    dependencies = [
        ("trips", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(names_to_codes, codes_to_names),
        migrations.AlterField(
            model_name="trip",
            name="country",
            field=django_countries.fields.CountryField(
                blank=True, max_length=2, verbose_name="country"
            ),
        ),
    ]
