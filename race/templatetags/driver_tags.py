from django import template

register = template.Library()


@register.simple_tag
def get_weight_penalty(driver):
    """Get the weight penalty for a driver, caching the database query result"""
    try:
        return driver.weight_penalty
    except Exception as e:
        print(f"Error getting weight penalty: {e}")
        return 0
