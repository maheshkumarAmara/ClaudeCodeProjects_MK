from pdf_engine.layouts.arrow_ecs_sau import ARROW_ECS_SAU_LAYOUT
from pdf_engine.layouts.exclusive_networks_south_africa import EXCLUSIVE_NETWORKS_SOUTH_AFRICA_LAYOUT
from pdf_engine.models import DistributorLayout

LAYOUTS: dict[str, DistributorLayout] = {
    "arrow-ecs-sau": ARROW_ECS_SAU_LAYOUT,
    "exclusive-networks-south-africa": EXCLUSIVE_NETWORKS_SOUTH_AFRICA_LAYOUT,
}


def get_layout(slug: str) -> DistributorLayout | None:
    return LAYOUTS.get(slug)
