"""Expense types become a list per trip, so travelers can add and remove their own.

Every existing trip gets the eight types it had before, and each expense keeps its type.
"""

import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models

# The old fixed types: code -> (name, emoji), in their old order.
OLD_TYPES = {
    "transport": ("Transport", "🚕"),
    "accommodation": ("Accommodation", "🏨"),
    "food": ("Food & drink", "🍜"),
    "medical": ("Hospital & medicine", "💊"),
    "translation": ("Translation", "💬"),
    "shopping": ("Shopping", "🛍️"),
    "activities": ("Activities", "🎟️"),
    "other": ("Other", "📦"),
}


def copy_types(apps, schema_editor):
    Trip = apps.get_model("trips", "Trip")
    Category = apps.get_model("expenses", "Category")
    Expense = apps.get_model("expenses", "Expense")
    for trip in Trip.objects.all():
        by_code = {
            code: Category.objects.create(trip=trip, name=name, emoji=emoji, position=i)
            for i, (code, (name, emoji)) in enumerate(OLD_TYPES.items())
        }
        for code, category in by_code.items():
            Expense.objects.filter(trip=trip, old_category=code).update(category=category)


def restore_codes(apps, schema_editor):
    Expense = apps.get_model("expenses", "Expense")
    names = {name: code for code, (name, _emoji) in OLD_TYPES.items()}
    for expense in Expense.objects.select_related("category"):
        name = expense.category.name if expense.category else ""
        expense.old_category = names.get(name, "other")
        expense.save(update_fields=["old_category"])


class Migration(migrations.Migration):
    dependencies = [
        ("expenses", "0005_expense_position"),
        ("trips", "0003_trip_settled_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="Category",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=40, verbose_name="name")),
                ("emoji", models.CharField(default="🏷️", max_length=16, verbose_name="icon")),
                ("position", models.PositiveIntegerField(default=0)),
                (
                    "trip",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="categories",
                        to="trips.trip",
                    ),
                ),
            ],
            options={"verbose_name": "type", "ordering": ["position", "id"]},
        ),
        migrations.AddConstraint(
            model_name="category",
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower("name"),
                models.F("trip"),
                name="category_name_unique_in_trip",
            ),
        ),
        migrations.RenameField(model_name="expense", old_name="category", new_name="old_category"),
        migrations.AddField(
            model_name="expense",
            name="category",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="expenses",
                to="expenses.category",
                verbose_name="type",
            ),
        ),
        migrations.RunPython(copy_types, restore_codes),
        migrations.RemoveField(model_name="expense", name="old_category"),
    ]
