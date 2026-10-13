"""Fill an empty database with a believable catalog.

build.sh runs this on every deploy, so it only ever acts on an empty catalog. Once
products exist it does nothing: stock is decremented by real orders and prices and
withdrawals are edited in the admin, and a deploy must never put those back.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Category, Product

CATEGORIES = [
    ("Kitchen", "kitchen"),
    ("Outdoors", "outdoors"),
    ("Desk", "desk"),
]

# (slug, name, category slug, price in minor units, stock, description)
PRODUCTS = [
    ("enamel-kettle", "Enamel kettle", "kitchen", 44900, 12,
     "Speckled enamel over steel, 1.5 litres. Takes a flame or an induction hob without fuss."),
    ("cast-iron-pan", "Cast iron pan", "kitchen", 69900, 7,
     "26 cm, pre-seasoned, oven-safe to 260 °C. Heavy enough to be the last pan you buy."),
    ("linen-apron", "Linen apron", "kitchen", 32900, 20,
     "Washed Belgian linen with a cross-back strap, so the weight sits on your shoulders."),
    ("stoneware-mug", "Stoneware mug", "kitchen", 17900, 0,
     "350 ml, reactive glaze, no two quite alike. Dishwasher safe despite appearances."),
    ("wool-blanket", "Wool blanket", "outdoors", 89900, 5,
     "Lambswool, 130 × 180 cm, woven in Gotland. Warm while damp, which matters in October."),
    ("thermos-flask", "Thermos flask", "outdoors", 39900, 15,
     "Vacuum steel, 750 ml, holds heat twelve hours. The lid doubles as a cup."),
    ("canvas-rucksack", "Canvas rucksack", "outdoors", 109900, 4,
     "Waxed cotton, 24 litres, leather base. Padded sleeve fits a 15-inch laptop."),
    ("head-torch", "Head torch", "outdoors", 24900, 30,
     "350 lumens, USB-C, red night mode. Runs six hours on full, far longer dimmed."),
    ("oak-desk-tidy", "Oak desk tidy", "desk", 27900, 9,
     "Solid oak, three slots and a tray, finished with hardwax oil."),
    ("brass-lamp", "Brass lamp", "desk", 119900, 3,
     "Unlacquered brass that will patina, articulated arm, dimmable warm LED."),
    ("linen-notebook", "Linen notebook", "desk", 14900, 40,
     "A5, 192 dot-grid pages, 100 gsm paper that takes fountain ink without bleeding."),
    ("felt-mousepad", "Felt mousepad", "desk", 9900, 0,
     "5 mm merino felt, 900 × 400 mm. Covers the keyboard and most of the desk with it."),
]


class Command(BaseCommand):
    help = "Create the demo catalog if the database has none. Never touches existing data."

    @transaction.atomic
    def handle(self, *args, **options):
        if Product.objects.exists():
            self.stdout.write("Catalog already has products; leaving it alone.")
            return

        categories = {}
        for name, slug in CATEGORIES:
            category, _ = Category.objects.get_or_create(slug=slug, defaults={"name": name})
            categories[slug] = category

        for slug, name, category_slug, price_minor, stock, description in PRODUCTS:
            Product.objects.create(
                slug=slug,
                name=name,
                category=categories[category_slug],
                price_minor=price_minor,
                stock=stock,
                description=description,
                image=f"products/{slug}.svg",
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(CATEGORIES)} categories and {len(PRODUCTS)} products."
            )
        )
