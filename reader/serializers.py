from rest_framework import serializers

from django.contrib.auth.models import User
from rest_framework import serializers

from django.contrib.auth.models import User

from rest_framework import serializers
from .models import User


class UserSerializer(serializers.ModelSerializer):
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'password', 'confirm_password']
        extra_kwargs = {'password': {'write_only': True}}

  
    def save(self):
        username = self.validated_data['username']
        first_name = self.validated_data['first_name']
        last_name = self.validated_data['last_name']
        email = self.validated_data['email']
        password = self.validated_data['password']
        password2= self.validated_data['confirm_password']
        
        if password != password2:
            raise serializers.ValidationError({'error' :"Passwords doesn't matched"})
        
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError({'error' :"Email Already exists"})
        
        account = User(username = username,email=email,first_name=first_name,last_name=last_name)
        print(account)
        account.set_password(password)
        account.is_active = False
        account.save()
        return account

    
class UserLoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True)