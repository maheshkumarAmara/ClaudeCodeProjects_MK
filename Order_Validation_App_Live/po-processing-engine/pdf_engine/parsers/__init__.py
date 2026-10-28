from pdf_engine.parsers.adn_distribution_gmbh import parse_template as parse_adn_distribution_gmbh
from pdf_engine.parsers.arrow_netherlands import parse_template as parse_arrow_netherlands
from pdf_engine.parsers.computer_gross_spa import parse_template as parse_computer_gross_spa
from pdf_engine.parsers.exclusive_networks_norway import parse_template as parse_exclusive_networks_norway
from pdf_engine.parsers.ingram_micro_canada import parse_template as parse_ingram_micro_canada
from pdf_engine.parsers.innocom_ltd import parse_template as parse_innocom_ltd
from pdf_engine.parsers.networld_corporation import parse_template as parse_networld_corporation
from pdf_engine.parsers.nextgen_distribution_pty_ltd import parse_template as parse_nextgen_distribution_pty_ltd
from pdf_engine.parsers.nox_co_ltd import parse_template as parse_nox_co_ltd

# Distributors whose template needs a custom reader instead of a coordinate
# layout. Each parser takes the template PDF path and returns
# {"fields": {...}, "line_items": [...]}.
PARSERS = {
    "ADN Distribution GmbH": parse_adn_distribution_gmbh,
    "Arrow (Netherlands)": parse_arrow_netherlands,
    "Computer Gross spa": parse_computer_gross_spa,
    "Exclusive Networks (Norway)": parse_exclusive_networks_norway,
    "Ingram Micro Canada": parse_ingram_micro_canada,
    "Innocom Ltd": parse_innocom_ltd,
    "Networld Corporation": parse_networld_corporation,
    "NOX Co.,LTD.": parse_nox_co_ltd,
    "NextGen Distribution Pty Ltd": parse_nextgen_distribution_pty_ltd,
}
