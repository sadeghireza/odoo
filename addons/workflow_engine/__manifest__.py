{
    "name": "Workflow Engine",
    "summary": "Model-agnostic workflow engine with versioned definitions",
    "version": "1.1.0",
    "category": "Tools",
    "license": "LGPL-3",
    "author": "Workflow Engine",
    "depends": ["base"],
    "data": [
        "security/workflow_security.xml",
        "security/workflow_default_groups.xml",
        "security/ir.model.access.csv",
        "views/workflow_engine_menu.xml",
        "data/ir_cron.xml",
    ],
    "demo": [
        "demo/workflow_demo.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "workflow_engine/static/src/js/condition_builder.js",
            "workflow_engine/static/src/js/workflow_designer.js",
            "workflow_engine/static/src/xml/workflow_designer.xml",
            "workflow_engine/static/src/scss/workflow_designer.scss",
        ],
        "web.assets_tests": [],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
