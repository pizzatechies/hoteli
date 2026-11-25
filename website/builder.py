"""Website builder helpers: page templates, section defaults and ordering."""

from django.db import transaction
from django.db.models import F, Max

from .models import Page, Section

K = Section.Kind
IMG = "https://images.unsplash.com/{}?auto=format&fit=crop&w=1600&q=70"

# Sensible starting content when a section is added, so staff edit rather than start blank.
SECTION_DEFAULTS = {
    K.HERO: {"title": "Your home away from home",
             "subtitle": "Comfortable rooms, great food and warm hospitality. Book direct and pay with M-Pesa.",
             "image_url": IMG.format("photo-1566073771259-6a8506099945"), "show_search": True},
    K.TEXT: {"title": "A heading", "body": "Write a few sentences here.\n\nBlank lines start a new paragraph."},
    K.IMAGE_TEXT: {"eyebrow": "About us", "title": "A warm welcome awaits",
                   "body": "Tell guests what makes your hotel special.",
                   "image_url": IMG.format("photo-1520250497591-112f2f40a3f4")},
    K.ROOMS: {"eyebrow": "Stay with us", "title": "Rooms & suites",
              "subtitle": "Comfortable, spotless rooms for every kind of trip.", "limit": 6},
    K.FACILITIES: {"eyebrow": "Everything you need", "title": "Facilities", "limit": 8, "background": "soft"},
    K.MENU: {"eyebrow": "Restaurant & bar", "title": "Taste of our kitchen", "limit": 6,
             "button_text": "Full menu", "button_url": "/dining/"},
    K.GALLERY: {"title": "Gallery", "items": "\n".join([
        IMG.format("photo-1631049307264-da0ec9d70304") + " | Standard room",
        IMG.format("photo-1590490360182-c33d57733427") + " | Deluxe room",
        IMG.format("photo-1414235077428-338989a2e8c0") + " | Restaurant",
    ])},
    K.FEATURES: {"title": "Why book direct", "items": "\n".join([
        "shield-check | Best rate | Lowest price when you book on our website.",
        "phone | Pay with M-Pesa | Approve the prompt on your phone – done.",
        "envelope-check | Instant confirmation | Your booking is confirmed by email right away.",
    ])},
    K.TESTIMONIALS: {"eyebrow": "Guest reviews", "title": "What our guests say", "background": "soft",
                     "items": "Paste a genuine guest review here | Guest name | City"},
    K.FAQ: {"title": "Frequently asked questions", "items": "\n".join([
        "What time is check-in? | Check-in is from 2pm and check-out by 10am.",
        "How do I pay? | Pay securely with M-Pesa when you book, or at the front desk.",
        "Is parking available? | Yes, free secure parking for all guests.",
    ])},
    K.CTA: {"title": "Ready for your stay?", "subtitle": "Check availability and book in under two minutes.",
            "button_text": "Book now", "button_url": "/book/", "background": "brand"},
    K.MAP: {"title": "Find us", "body": "We are a short drive from the city centre."},
    K.CONTACT: {"title": "Send us a message", "subtitle": "We usually reply within a few hours."},
}

PAGE_TEMPLATES = {
    "blank": {"label": "Blank page", "sections": []},
    "home": {"label": "Homepage", "sections": [
        (K.HERO, {}),
        (K.ROOMS, {}),
        (K.FACILITIES, {}),
        (K.IMAGE_TEXT, {"eyebrow": "About us", "title": "Comfort, the Kenyan way",
                        "body": "We are an independent hotel offering comfortable, secure accommodation for business "
                                "and leisure travellers.\n\nEnjoy free Wi-Fi, a restaurant serving local and "
                                "international dishes, secure parking and a friendly team around the clock.",
                        "button_text": "See our menu", "button_url": "/dining/"}),
        (K.FEATURES, {"eyebrow": "Book direct", "title": "Book & pay in 3 easy steps", "background": "soft",
                      "items": "calendar-check | Choose your dates | Pick a room and see the full price upfront.\n"
                               "person-vcard | Enter your details | Just your name, phone and email.\n"
                               "phone | Approve on M-Pesa | Enter your PIN on the prompt – confirmed instantly."}),
        (K.CTA, {}),
    ]},
    "about": {"label": "About us", "sections": [
        (K.IMAGE_TEXT, {"eyebrow": "Our story", "title": "About us"}),
        (K.FEATURES, {}),
        (K.GALLERY, {}),
        (K.CTA, {}),
    ]},
    "events": {"label": "Events & conferences", "sections": [
        (K.IMAGE_TEXT, {"eyebrow": "Meetings & events", "title": "Conferences, workshops & celebrations",
                        "body": "Flexible rooms for 10 to 120 guests, with projector, sound system, fast Wi-Fi and "
                                "full catering from our kitchen.\n\nAsk about day-conference packages, including "
                                "tea breaks and lunch.",
                        "image_url": IMG.format("photo-1505373877841-8d25f7d46678"),
                        "button_text": "Request a quote", "button_url": "#contact"}),
        (K.FEATURES, {"title": "Included in every package", "background": "soft",
                      "items": "easel | Projector & screen | HD projector, flip charts and stationery.\n"
                               "wifi | Fast Wi-Fi | Fibre internet for all delegates.\n"
                               "cup-hot | Catering | Tea breaks, buffet lunch and dinner options.\n"
                               "p-circle | Parking | Free, secure parking for delegates."}),
        (K.FAQ, {"items": "How many people can you host? | From 10 to 120 guests depending on the layout.\n"
                          "Do you offer accommodation for delegates? | Yes – ask about group room rates.\n"
                          "Can we pay with M-Pesa? | Yes, deposits and balances can be paid by M-Pesa."}),
        (K.CONTACT, {"title": "Request a quote"}),
    ]},
    "contact": {"label": "Contact & location", "sections": [
        (K.CONTACT, {"title": "Get in touch"}),
        (K.MAP, {}),
    ]},
}


def next_order(page):
    return (page.sections.aggregate(m=Max("order"))["m"] or 0) + 10


def add_section(page, kind, overrides=None, position=None):
    data = {**SECTION_DEFAULTS.get(kind, {}), **(overrides or {})}
    return Section.objects.create(page=page, kind=kind, order=position or next_order(page), **data)


@transaction.atomic
def create_page(*, title, template="blank", **page_fields):
    page = Page.objects.create(title=title, **page_fields)
    for kind, overrides in PAGE_TEMPLATES.get(template, PAGE_TEMPLATES["blank"])["sections"]:
        add_section(page, kind, overrides)
    return page


def renumber(page):
    for i, section in enumerate(page.sections.order_by("order", "id")):
        if section.order != (i + 1) * 10:
            Section.objects.filter(pk=section.pk).update(order=(i + 1) * 10)


@transaction.atomic
def move_section(section, direction):
    renumber(section.page)
    siblings = list(section.page.sections.order_by("order", "id"))
    idx = next(i for i, s in enumerate(siblings) if s.pk == section.pk)
    swap = idx - 1 if direction == "up" else idx + 1
    if 0 <= swap < len(siblings):
        a, b = siblings[idx], siblings[swap]
        Section.objects.filter(pk=a.pk).update(order=b.order)
        Section.objects.filter(pk=b.pk).update(order=a.order)


@transaction.atomic
def duplicate_section(section):
    renumber(section.page)
    section.refresh_from_db()
    section.page.sections.filter(order__gt=section.order).update(order=F("order") + 10)
    clone = Section.objects.get(pk=section.pk)
    clone.pk = None
    clone.order = section.order + 10
    clone.save()
    return clone


@transaction.atomic
def duplicate_page(page):
    clone = Page.objects.get(pk=page.pk)
    clone.pk = None
    clone.slug = ""
    clone.title = f"{page.title} (copy)"
    clone.is_home = False
    clone.is_published = False
    clone.save()
    for section in page.sections.all():
        section.pk = None
        section.page = clone
        section.save()
    return clone
