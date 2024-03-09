from django.shortcuts import render,redirect

# Create your views here.
from rest_framework import viewsets,generics

from .serializers import UserSerializer,UserLoginSerializer
from rest_framework.views import APIView
from rest_framework.response import Response

# token
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_decode,urlsafe_base64_encode
from django.utils.encoding import force_bytes 
from rest_framework.authtoken.models import Token

from django.contrib.auth.models import User
from django.contrib.auth import authenticate,login,logout 

# for sending email 
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from rest_framework.decorators import action
from django.contrib.auth import get_user_model

class UserView(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer

    @action(detail=False, methods=['GET'])
    def is_superuser(self, request, pk=None):
        user_id = pk
        try:
            user = User.objects.get(pk=user_id)
            is_superuser = user.is_superuser
            return Response({'user_id': user_id, 'is_superuser': is_superuser})
        except User.DoesNotExist:
            return Response({'error': 'User does not exist'})
        
class UserRegistrationAPIView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    def post(self,request):
        serializer = self.serializer_class(data=request.data)
        
        if serializer.is_valid():
            user = serializer.save()
            print(user)
            token = default_token_generator.make_token(user)
            print("token ",token)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            print("uid ",uid)
            confirm_link = f"https://somoysondhan-backend.onrender.com/user/active/{uid}/{token}"
            email_subject = "Confirm your Email"
            email_body = render_to_string("confirm_email.html",{"confirm_link":confirm_link})
            email = EmailMultiAlternatives(email_subject, '',to=[user.email])
            email.attach_alternative(email_body,"text/html")
            email.send()
            return Response("Check your mail for confirmation")
        return Response(serializer.errors)
    
def activate(request,uid64,token):
    try: 
        uid = urlsafe_base64_decode(uid64).decode()
        user = User._default_manager.get(pk=uid)
    except(User.DoesNotExist):
        user = None
        
    if user is not None and default_token_generator.check_token(user,token):
        user.is_active = True
        user.save()
        return redirect('https://65ec4bc538e71193265ec179--somoysondhan.netlify.app/login.html')
    else:
        return redirect('https://65ec4bc538e71193265ec179--somoysondhan.netlify.app/register.html')
    

class UserLoginApiView(APIView):
    def post(self,request):
        serializer = UserLoginSerializer(data=self.request.data)
        if serializer.is_valid():
            username = serializer.validated_data['username']
            password = serializer.validated_data['password']
            User = get_user_model()
            try:
                user = User.objects.get(username=username)
            except User.DoesNotExist:
                return Response({'error': 'User not found'})
            
            user = authenticate(username=username, password=password)
            
            if user:
                token,_ = Token.objects.get_or_create(user=user)
                print(token)
                print(_)
                login(request,user)
                return Response({'token':token.key,'user_id':user.id})
            else:
                return Response({'error':'Password is incorrect'})
            
        return Response(serializer.error) 
    
class UserLogoutView(APIView):
    def get(self,request):
        request.user.auth_token.delete()
        logout(request)
        return redirect('login')