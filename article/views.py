from rest_framework import viewsets, status
from rest_framework.response import Response
from .models import Article, Review,Category
from .serializers import ArticleSerializer, ReviewSerializer,CategorySerializer
from rest_framework.decorators import action
from django.contrib.auth.models import User

# for sending email 
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from rest_framework.decorators import action
from django.contrib.auth import get_user_model


def send_transaction_email(review,subject,template):
        user = User.objects.get(id=review['user'])
        article = Article.objects.get(id=review['article'])
        print(review,user)
        message = render_to_string(template,{
            'review':review, 
            'article':article
        })
        send_email = EmailMultiAlternatives(subject,'',to=[user.email])
        send_email.attach_alternative(message,"text/html")
        send_email.send()
        
class ArticleViewSet(viewsets.ModelViewSet):
    queryset = Article.objects.all()
    serializer_class = ArticleSerializer
    
    def list(self, request):
        category_name = request.query_params.get('category')
        if category_name:
            articles = Article.objects.filter(categories__slug=category_name).order_by('-publishing_time')
        else:
            articles = Article.objects.all().order_by('-publishing_time')
        serializer = self.get_serializer(articles, many=True)
        return Response(serializer.data)


    def retrieve(self, request, pk=None):
        article = self.get_object()
        serializer = self.get_serializer(article)
        return Response(serializer.data)
    
    def get_reviews_by_article(self, request, pk=None):
        article = self.get_object()
        reviews = Review.objects.filter(article=article)
        serializer = ReviewSerializer(reviews, many=True)
        return Response(serializer.data)

    def create_review(self, request, pk=None):
        review_data = {
            'rating': request.data.get('rating'),
            'comment': request.data.get('comment'),
            'article': request.data.get('article'),
            'user': request.data.get('user'),
        }
        print(review_data['user'])
        serializer = ReviewSerializer(data=review_data)
        if serializer.is_valid():
            serializer.save()
            send_transaction_email(review_data,"Review Message","Review_email.html")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['GET'])
    def related(self, request, pk=None):
        article = self.get_object()
        categories = article.categories.all()
        
        related_articles = Article.objects.filter(categories__in=categories).exclude(id=article.id).order_by('-publishing_time')

        
        related_articles = related_articles.distinct()

                
        serializer = self.get_serializer(related_articles, many=True)
        return Response(serializer.data)
    
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)
    
    def destroy(self, request, pk=None):
        article = self.get_object()
        article.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer