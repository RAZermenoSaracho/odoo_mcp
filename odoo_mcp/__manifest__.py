{
    "name": "Odoo Mcp",
    "version": "19.0.1.0.0",
    "category": "Uncategorized",
    "summary": "Reusable Model Context Protocol (MCP) interface for Odoo 19: exposes selected Odoo capabilities to authenticated MCP clients under normal ORM security",
    "description": """
Odoo Mcp
========

Reusable Model Context Protocol (MCP) interface for Odoo 19: exposes selected Odoo capabilities to authenticated MCP clients under normal ORM security
    """,
    "author": "Ricardo Zermeño",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "application": False,
}
