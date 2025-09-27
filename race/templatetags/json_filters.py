from django import template
import json

register = template.Library()


@register.filter
def jsonify(value):
    """Convert Python object to JSON string"""
    return json.dumps(value)
