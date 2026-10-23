from django.http import HttpResponse
from django.urls import path
from django.views import View
from rest_framework.response import Response
from rest_framework.views import APIView

from account_ratelimit.decorators import ratelimit


@ratelimit("every-use", methods=["POST"])
def fbv(request):
    return HttpResponse("ok")


@ratelimit("every-use")
class CBV(View):
    def get(self, request):
        return HttpResponse("ok")


class Api(APIView):
    ratelimit_rule = "every-use"

    def get(self, request):
        return Response({"ok": True})


class ApiUnthrottled(APIView):
    def get(self, request):
        return Response({"ok": True})


@ratelimit("every-use")
def api_fbv(request):
    return HttpResponse("ok")


def page(request):
    return HttpResponse("page")


urlpatterns = [
    path("fbv/", fbv),
    path("cbv/", CBV.as_view()),
    path("api/drf/", Api.as_view()),
    path("api/free/", ApiUnthrottled.as_view()),
    path("api/fbv/", api_fbv),
    path("pages/one/", page),
    path("pages/free/", page),
]
