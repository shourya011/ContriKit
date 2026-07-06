from django.shortcuts import render, get_object_or_404
from django.db.models import Q
from .models import Template


def template_list_view(request):
    templates = Template.objects.all()
    category = request.GET.get("category")
    search = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "category")

    if category and category != "all":
        templates = templates.filter(category=category)

    if search:
        templates = templates.filter(
            Q(title__icontains=search)
            | Q(category__icontains=search)
            | Q(tags__icontains=search)
            | Q(description__icontains=search)
        )

    if sort == "alpha":
        templates = templates.order_by("title")
    elif sort == "newest":
        templates = templates.order_by("-created_at")
    else:
        templates = templates.order_by("category", "title")

    categories = Template.CATEGORY_CHOICES
    selected_category = category if category else "all"

    context = {
        "templates": templates,
        "categories": categories,
        "selected_category": selected_category,
        "search_query": search,
        "current_sort": sort,
    }
    return render(request, "templates_app/template_list.html", context)


def template_detail_view(request, slug):
    template = get_object_or_404(Template, slug=slug)
    related = (
        Template.objects.filter(category=template.category)
        .exclude(id=template.id)[:3]
    )
    context = {
        "template": template,
        "related_templates": related,
    }
    return render(request, "templates_app/template_detail.html", context)