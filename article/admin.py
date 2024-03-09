from django.contrib import admin
from .models import Category, Article, Review

@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ('id', 'headline', 'publishing_time')
    filter_horizontal = ('categories',) 

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name')

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ('id', 'article', 'user', 'rating', 'created_at')
