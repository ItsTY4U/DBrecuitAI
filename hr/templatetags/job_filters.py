from django import template

register = template.Library()


@register.filter
def splitlines_clean(value):
    if not value:
        return []

    return [
        line.strip()
        for line in str(value).splitlines()
        if line.strip()
    ]