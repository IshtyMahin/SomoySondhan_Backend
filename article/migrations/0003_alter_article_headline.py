# Generated by Django 5.0.1 on 2024-03-07 18:33

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('article', '0002_alter_article_categories_alter_review_rating'),
    ]

    operations = [
        migrations.AlterField(
            model_name='article',
            name='headline',
            field=models.CharField(max_length=1000),
        ),
    ]
