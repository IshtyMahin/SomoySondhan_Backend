from rest_framework.routers import DefaultRouter

from django.urls import path,include
from .views import UserView,UserRegistrationAPIView,activate,UserLoginApiView,UserLogoutView

# router = DefaultRouter(trailing_slash=False)
router = DefaultRouter()

router.register('list',UserView)

urlpatterns = [
    path("",include(router.urls)),
    path("register/", UserRegistrationAPIView.as_view(), name='register'),
    path("login/",UserLoginApiView.as_view(), name='login'),
    path("logout/",UserLogoutView.as_view(), name='logout'),
    path('active/<uid64>/<token>/',activate,name='activate'),
    path('<int:pk>/is_superuser/', UserView.as_view({'get': 'is_superuser'}), name='is_superuser'),
]
