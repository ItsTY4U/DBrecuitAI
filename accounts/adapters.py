from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from .models import ApplicantProfile

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        
        if sociallogin.account.extra_data.get("email"):
            user.email = sociallogin.account.extra_data.get("email")
            user.save(update_fields=["email"])
        
        ApplicantProfile.objects.get_or_create(
            user=user
        )
        
        return user