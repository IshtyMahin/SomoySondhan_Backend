# models.py
from django.db import models
from django.db.models.signals import post_save,pre_save
from django.dispatch import receiver
from django.utils.text import slugify
from django.utils import timezone 

class Category(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=100, unique=True, null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.slug is None:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    
class Article(models.Model):
    headline = models.CharField(max_length=1000)
    body = models.TextField()
    categories = models.ManyToManyField(Category, related_name='articles',default='Latest')
    publishing_time = models.DateTimeField(auto_now_add=True)
    total_ratings = models.IntegerField(default=0)
    total_stars = models.IntegerField(default=0)
    
    def formatted_publishing_time(self):
        return self.publishing_time.strftime('%Y-%m-%d %H:%M:%S')
    
    def __str__(self):
        return self.headline

class Review(models.Model):
    RATING_CHOICES = (
        (1, '1 star'),
        (2, '2 stars'),
        (3, '3 stars'),
        (4, '4 stars'),
    )
    article = models.ForeignKey(Article, related_name='reviews', on_delete=models.CASCADE)
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
    rating = models.IntegerField(choices=RATING_CHOICES)
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return self.comment

@receiver(post_save, sender=Review)
def update_article_rating(sender, instance, **kwargs):
    article = instance.article
    reviews = article.reviews.all()
    total_ratings = reviews.count()
    total_stars = sum(review.rating for review in reviews)
    article.total_ratings = total_ratings
    article.total_stars = total_stars
    article.save()
