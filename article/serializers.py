# serializers.py
from rest_framework import serializers
from .models import Article, Review,Category

class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = '__all__'

class ArticleSerializer(serializers.ModelSerializer):
    categories = serializers.SlugRelatedField(
        queryset=Category.objects.all(),
        many=True,
        slug_field='name'
    )
    reviews = ReviewSerializer(many=True, read_only=True)
    total_ratings = serializers.IntegerField(read_only=True)
    average_rating = serializers.SerializerMethodField()
    star_counts = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = ['id', 'headline', 'body', 'categories', 'publishing_time', 'reviews', 'total_ratings', 'average_rating', 'star_counts']

    def get_average_rating(self, obj):
        if obj.total_ratings > 0:
            return obj.total_stars / obj.total_ratings
        else:
            return 0
        
    def get_star_counts(self, obj):
        star_counts = {1: 0, 2: 0, 3: 0, 4: 0}
        for review in obj.reviews.all():
            if review.rating in star_counts:
                star_counts[review.rating] += 1
        return star_counts

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name']