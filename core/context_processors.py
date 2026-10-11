from core.models import Category


def navigation(request):
    """Category nav appears in the site header, so every page needs it.

    A context processor rather than a repeated line in each view: forgetting it is
    how the nav silently vanished from the product detail page.
    """
    return {"categories": Category.objects.all()}
