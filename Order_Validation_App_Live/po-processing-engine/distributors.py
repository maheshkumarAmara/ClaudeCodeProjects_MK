"""The one place that lists the distributors the engine knows about.

Adding a distributor means adding one Distributor entry below (plus its parser /
generator / layout modules and sample PDF under data/templates/<slug>/).

Code is referenced as "module:attribute" strings and only imported when it is
used (see resolve()). That keeps this module free of project imports, so config,
extractor, generator and salesforce_client can all import it without a cycle.
validate() imports everything once and is called when the app starts, so a typo
here fails at startup instead of on the first request for that distributor.

Order matters: it is the order of GET /api/distributors and so of the dropdown.
The slug is also the folder name under data/templates/ and data/generated/.
"""

import importlib
from dataclasses import dataclass


@dataclass(frozen=True)
class Distributor:
    slug: str
    name: str                       # display name; Salesforce's Distributor_Lookup__r.Name is matched against it
    hidden: bool = False            # kept in the API, left out of the UI dropdown
    parser: str | None = None       # "module:fn(path) -> {fields, line_items}", else the layout path is used
    generator: str | None = None    # "module:fn(fields, line_items) -> bytes", else generator.generate_po + layout
    layout: str | None = None       # "module:DistributorLayout"
    sf_mapper: str | None = None    # "module:fn(quote, account, order) -> fields"; None = default mapper
    sf_line_hook: str | None = None # "module:fn(item, quote_line_record)" run on every pulled line item


_P = "pdf_engine.parsers."
_G = "pdf_engine.generator_"

REGISTRY: tuple[Distributor, ...] = (
    # Legacy placeholders and the two layout-based distributors (hidden from the dropdown).
    Distributor("pt-synnex-metrodata-indonesia", "PT. Synnex Metrodata Indonesia", hidden=True),
    Distributor("pt-ecs-indo-jaya", "PT. ECS Indo Jaya", hidden=True),
    Distributor("hcl", "HCL POs", hidden=True),
    Distributor("exclusive-networks-turkey", "Exclusive Networks Turkey", hidden=True),
    Distributor(
        "exclusive-networks-south-africa",
        "Exclusive Networks (South Africa)",
        hidden=True,
        layout="pdf_engine.layouts.exclusive_networks_south_africa:EXCLUSIVE_NETWORKS_SOUTH_AFRICA_LAYOUT",
        sf_mapper="salesforce_client:_map_fields_exclusive_networks_south_africa",
    ),
    Distributor(
        "arrow-ecs-sau",
        "ARROW E.C.S., SAU",
        hidden=True,
        layout="pdf_engine.layouts.arrow_ecs_sau:ARROW_ECS_SAU_LAYOUT",
    ),
    # Slugs below match their data/templates/ folder names exactly.
    Distributor(
        "ADN Distribution GmbH",
        "ADN Distribution GmbH",
        parser=_P + "adn_distribution_gmbh:parse_template",
        generator=_G + "adn:generate_adn_po",
    ),
    Distributor(
        "Arrow (Netherlands)",
        "Arrow ECS BV (Netherlands)",
        parser=_P + "arrow_netherlands:parse_template",
        generator=_G + "arrow_netherlands:generate_arrow_netherlands_po",
    ),
    Distributor(
        "Computer Gross spa",
        "Computer Gross spa",
        parser=_P + "computer_gross_spa:parse_template",
        generator=_G + "computer_gross_spa:generate_computer_gross_spa_po",
        sf_mapper="salesforce_client:_map_fields_computer_gross_spa",
    ),
    Distributor(
        "Exclusive Networks (Norway)",
        "Exclusive Networks (Norway)",
        parser=_P + "exclusive_networks_norway:parse_template",
        generator=_G + "exclusive_networks_norway:generate_exclusive_networks_norway_po",
    ),
    Distributor("HCL America, Inc.", "HCL America, Inc."),
    Distributor(
        "Ingram Micro Canada",
        "Ingram Micro Canada",
        parser=_P + "ingram_micro_canada:parse_template",
        generator=_G + "ingram_micro_canada:generate_ingram_micro_canada_po",
        sf_mapper="salesforce_client:_map_fields_ingram_micro_canada",
    ),
    Distributor(
        "Innocom Ltd",
        "Innocom Ltd",
        parser=_P + "innocom_ltd:parse_template",
        generator=_G + "innocom_ltd:generate_innocom_ltd_po",
    ),
    Distributor("iValue InfoSolutions Limited", "iValue InfoSolutions Limited"),
    Distributor(
        "Networld Corporation",
        "Networld Corporation",
        parser=_P + "networld_corporation:parse_template",
        generator=_G + "networld_corporation:generate_networld_corporation_po",
    ),
    Distributor(
        "NextGen Distribution Pty Ltd",
        "NextGen Distribution Pty Ltd",
        parser=_P + "nextgen_distribution_pty_ltd:parse_template",
        generator=_G + "nextgen_distribution_pty_ltd:generate_nextgen_distribution_pty_ltd_po",
        sf_mapper="salesforce_client:_map_fields_nextgen_distribution_pty_ltd",
        sf_line_hook="salesforce_client:_apply_nextgen_pricing",
    ),
    Distributor(
        "NOX Co.,LTD.",
        "NOX Co.,LTD.",
        parser=_P + "nox_co_ltd:parse_template",
        generator=_G + "nox_co_ltd:generate_nox_co_ltd_po",
    ),
)

_BY_SLUG = {d.slug: d for d in REGISTRY}
if len(_BY_SLUG) != len(REGISTRY):
    raise RuntimeError("distributors.REGISTRY has a duplicate slug")


def get(slug: str | None) -> Distributor | None:
    return _BY_SLUG.get(slug) if slug is not None else None


def names() -> dict[str, str]:
    """slug -> display name, in registry order (what config.DISTRIBUTORS exposes)."""
    return {d.slug: d.name for d in REGISTRY}


def resolve(ref: str):
    """Import and return the object named by a "module:attribute" string."""
    module_name, _, attr = ref.partition(":")
    return getattr(importlib.import_module(module_name), attr)


def _resolved(slug: str, field: str):
    d = get(slug)
    ref = getattr(d, field) if d is not None else None
    return resolve(ref) if ref else None


def get_parser(slug: str):
    return _resolved(slug, "parser")


def get_generator(slug: str):
    return _resolved(slug, "generator")


def get_layout(slug: str):
    return _resolved(slug, "layout")


def get_sf_mapper(slug: str | None):
    return _resolved(slug, "sf_mapper") if slug is not None else None


def get_sf_line_hook(slug: str | None):
    return _resolved(slug, "sf_line_hook") if slug is not None else None


def validate() -> None:
    """Import everything the registry points at; raise on the first thing that doesn't resolve.

    Also checks that a generator's own SLUG constant matches its registry slug,
    since the generator uses it to find its template and output folder.
    """
    for d in REGISTRY:
        for field in ("parser", "generator", "layout", "sf_mapper", "sf_line_hook"):
            ref = getattr(d, field)
            if not ref:
                continue
            try:
                obj = resolve(ref)
            except (ImportError, AttributeError) as exc:
                raise RuntimeError(f"distributors.REGISTRY: '{d.slug}' {field}='{ref}' does not resolve: {exc}") from exc
            if field == "generator":
                module_slug = getattr(importlib.import_module(obj.__module__), "SLUG", None)
                if module_slug is not None and module_slug != d.slug:
                    raise RuntimeError(
                        f"distributors.REGISTRY: '{d.slug}' generator {ref} uses SLUG '{module_slug}'"
                    )
