import re

from rest_framework import status
from rest_framework.generics import RetrieveUpdateAPIView, CreateAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import ValidationError
from requests.exceptions import HTTPError
from .backends import JWTAuthentication

from social_django.utils import load_backend, load_strategy
from social_core.backends.oauth import BaseOAuth1, BaseOAuth2
from social_core.exceptions import MissingBackend, AuthTokenError, AuthForbidden

from .renderers import UserJSONRenderer
from .serializers import (
    LoginSerializer, RegistrationSerializer, UserSerializer,SocialSignUpSerializer
)
from django.contrib.auth.hashers import check_password

from .models import User

auth = JWTAuthentication()

class RegistrationAPIView(CreateAPIView):
    """register a user """
    # Allow any user (authenticated or not) to hit this endpoint.
    permission_classes = (AllowAny,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = RegistrationSerializer

    def post(self, request):
        user = request.data
        # The create serializer, validate serializer, save serializer pattern
        # below is common and you will see it a lot throughout this course and
        # your own work later on. Get familiar with it.
        serializer = self.serializer_class(data=user, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        success_message = {"success" : "Please check your email for a link to complete your registration"}
        return Response(success_message, status=status.HTTP_201_CREATED)


class LoginAPIView(CreateAPIView):
    """login a user """
    permission_classes = (AllowAny,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = LoginSerializer

    def post(self, request):
        user = request.data
        # Notice here that we do not call `serializer.save()` like we did for
        # the registration endpoint. This is because we don't actually have
        # anything to save. Instead, the `validate` method on our serializer
        # handles everything we need.
        serializer = self.serializer_class(data=user)
        serializer.is_valid(raise_exception=True)

        return Response(serializer.data, status=status.HTTP_200_OK)


class UserRetrieveUpdateAPIView(RetrieveUpdateAPIView):
    permission_classes = (IsAuthenticated,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = UserSerializer

    def get(self, request, *args, **kwargs):
        """retreive user details"""
        # There is nothing to validate or save here. Instead, we just want the
        # serializer to handle turning our `User` object into something that
        # can be JSONified and sent to the client.
        serializer = self.serializer_class(request.user)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, *args, **kwargs):
        """update user details"""
        serializer_data = request.data

        # Here is that serialize, validate, save pattern we talked about
        # before.
        serializer = self.serializer_class(
            request.user, data=serializer_data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=status.HTTP_200_OK)


class ActivateAPIView(RetrieveAPIView):
    permission_classes = (AllowAny,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = LoginSerializer

    def get(self, request, token):
        """activate account"""
        user = auth.authenticate_credentials(request, token)
        if user[0].is_activated:
            message = {"message": "Your account has already been activated."}
            return Response(message, status=status.HTTP_200_OK)
        user[0].is_activated = True
        user[0].save()
        message = {"message": "Your account has been activated successfully"}
        return Response(message, status=status.HTTP_200_OK)

class ResendActivationEmailAPIView(CreateAPIView):
    permission_classes = (AllowAny,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = UserSerializer

    def post(self, request):
        """re-send account activation link"""
        serializer = self.serializer_class(request.user)
        email = request.data.get('email', None)

        if not email:
            message = {"message": "Please provide an email address"}
            return Response(message, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(email)
        user = serializer.get_user(email=email)
        token = user.token
        serializer.resend_confirmation_email(email, token, request)
        message = {"message": "Success, an activation link has been re-sent to your email."}
        return Response(message, status=status.HTTP_200_OK)


class ResetPasswordAPIView(CreateAPIView):
    permission_classes = (AllowAny,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = UserSerializer

    def post(self, request):
        """send reset password link"""
        email = request.data.get('email', None)
        if not email:
            message = {"message": "Please provide an email address"}
            return Response(message, status=status.HTTP_200_OK)
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(email)
        user = serializer.get_user(email=email)
        if not user.is_activated:
            message = {"message": "Please activate your account to continue"}
            return Response(message, status=status.HTTP_400_BAD_REQUEST)
        token = user.token
        serializer.reset_password(email, token, request)
        message = {"message": "An email has been sent to your account"}
        return Response(message, status=status.HTTP_200_OK)


class UpdateUserAPIView(RetrieveUpdateAPIView):
    permission_classes = (AllowAny,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = UserSerializer

    def put(self, request, token):
        """reset password route"""
        user = auth.authenticate_credentials(request, token)
        password = request.data.get('password', None)
        if not password:
            message = {"message": "Please provide a password"}
            return Response(message, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(password)
        if check_password(password, user[0].password):
            message = {"message": "Your new password can't be the same as your old password"}
            return Response(message, status=status.HTTP_400_BAD_REQUEST)
        user[0].set_password(password)
        user[0].save()
        message = {"message": "Your password has been updated successfully"}
        return Response(message, status=status.HTTP_200_OK)


class SocialSignUp(CreateAPIView):
    permission_classes = (AllowAny,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = SocialSignUpSerializer


    def post(self, request, *args, **kwargs):
        """ interrupt social_auth authentication pipeline"""
        #pass the request to serializer to make it a python object
        #serializer also catches errors of blank request objects
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        provider = serializer.data.get('provider', None)
        strategy = load_strategy(request) #creates the app instance

        if request.user.is_anonymous: #make sure the user is not anonymous
            user=None
        else:
            user=request.user


        try:
            #load backend with strategy and provider from settings(AUTHENTICATION_BACKENDS)
            backend = load_backend(strategy=strategy, name=provider, redirect_uri=None)

        except MissingBackend as error:

            return Response({
                "errors": str(error)
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            #check type of oauth provide e.g facebook is BaseOAuth2 twitter is BaseOAuth1
            if isinstance(backend, BaseOAuth1):
                #oath1 passes access token and secret
                access_token = {
                        "oauth_token": serializer.data.get('access_token'),
                        "oauth_token_secret": serializer.data.get('access_token_secret'),
                        }

            elif isinstance(backend, BaseOAuth2):
                #oauth2 only has access token
                access_token = serializer.data.get('access_token')

        except HTTPError as error:
            return Response({
                "error": {
                    "access_token": "invalid token",
                    "details": str(error)
                }
            }, status=status.HTTP_400_BAD_REQUEST)

        except AuthTokenError as error:
             return Response({
               "error":"invalid credentials",
               "details": str(error)
            }, status=status.HTTP_400_BAD_REQUEST)


        try:
            #authenticate the current user
            #social pipeline associate by email handles already associated exception
            authenticated_user = backend.do_auth(access_token, user=user)

        except HTTPError as error:
            #catch any error as a result of the authentication
            return Response({
                "error" : "invalid token",
                "details":str(error)
                },status=status.HTTP_400_BAD_REQUEST)

        except AuthForbidden as error:
            return Response({
                "error" : "invalid token",
                "details":str(error)
                },status=status.HTTP_400_BAD_REQUEST)

        if authenticated_user and authenticated_user.is_active:
            #Check if the user you intend to authenticate is active

            headers = self.get_success_headers(serializer.data)
            response = {"email":authenticated_user.email,
                        "username":authenticated_user.username,
                        "token":authenticated_user.token}

            return Response(response,status=status.HTTP_200_OK,
                                headers=headers)
        else:
            return Response({"errors": "Could not authenticate"},
                            status=status.HTTP_400_BAD_REQUEST)
