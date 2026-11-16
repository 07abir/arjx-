"""MarketPilot AI local Streamlit dashboard."""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import streamlit as st

from agents.manager import run_product_workflow
from config import get_settings
from database.db import initialize_database
from database.products import create_product, get_product, list_products, update_product
from database.workflows import get_workflow, list_product_workflows, update_workflow
from services.pricing import PricingInput, PricingResult, calculate_pricing
from services.product_images import delete_product, save_product_image


NAVIGATION = (
    ("Dashboard", ":material/dashboard:", "dashboard", "Database-backed product and workflow overview."),
    ("Add Product", ":material/add_box:", "add-product", "Add seller-provided product details and validated images."),
    ("AI Product Studio", ":material/auto_awesome:", "ai-product-studio", "Run the Google ADK workflow and inspect grounded outputs."),
    ("Pricing Intelligence", ":material/monitoring:", "pricing-intelligence", "Calculate product pricing with the deterministic Python engine."),
    ("Marketplace Distribution", ":material/storefront:", "marketplace-distribution", "Review and approve marketplace previews without publishing."),
    ("Marketing Center", ":material/campaign:", "marketing-center", "Edit, save, and copy generated marketing content."),
    ("Product History", ":material/history:", "product-history", "Inspect products and previously saved workflow attempts."),
)

DEMO_PRODUCT_ID = "DEMO"
DEMO_PRODUCT_DEFAULTS = {
    "id": DEMO_PRODUCT_ID,
    "name": "Handmade Leather Wallet",
    "category": "Fashion",
    "description": "Sample product for the MarketPilot AI hackathon walkthrough.",
    "specifications": "Material: Leather\nColour: Brown\nTarget audience: Men",
    "manufacturing_cost": 350.0,
    "packaging_cost": 15.0,
    "shipping_cost": 40.0,
    "fixed_marketplace_fees": 10.0,
    "commission_rate": 0.10,
    "desired_profit_margin": 0.25,
    "sku": "DEMO-WALLET-001",
    "target_price": None,
    "images": [],
    "created_at": "Demo sample — not saved to SQLite",
}

AGENT_LABELS = {
    "product_analysis": "Product Analysis Agent",
    "description": "Description Generation Agent",
    "marketing": "Marketing Agent",
    "pricing_engine": "Pricing Engine",
    "marketplace": "Marketplace Agent",
}


def dashboard_metrics(products, workflows):
    """Compute dashboard KPIs solely from persisted records."""
    return {
        "products": len(products),
        "completed": sum(item.get("status") == "completed" for item in workflows),
        "marketplace_previews": sum(len(item.get("marketplace_previews") or {}) for item in workflows),
        "attention": sum(item.get("status") in {"partial", "failed"} for item in workflows),
    }


def agent_statuses(workflow=None, active=None):
    """Infer saved step statuses from actual outputs/errors, then apply live events."""
    errors = {error.get("agent"): error for error in (workflow or {}).get("errors", [])}
    fields = {
        "product_analysis": "product_analysis",
        "description": "description",
        "marketing": "marketing",
        "pricing_engine": "pricing",
        "marketplace": "marketplace_previews",
    }
    statuses = {}
    is_demo = bool((workflow or {}).get("is_demo"))
    for key, output_key in fields.items():
        if is_demo:
            statuses[key] = "simulated" if workflow.get(output_key) else "pending"
        elif active and key in active:
            statuses[key] = {"complete": "completed", "error": "failed", "retrying": "running"}.get(active[key], active[key])
        elif workflow and workflow.get(output_key) is not None:
            statuses[key] = "completed"
        elif workflow and key in errors:
            statuses[key] = "failed"
        else:
            statuses[key] = "pending"
    return statuses


def _demo_product():
    product = dict(DEMO_PRODUCT_DEFAULTS)
    product.update(st.session_state.get("demo_product", {}))
    return product


def _capture_demo_images(uploads):
    """Keep uploaded demo image bytes in session state without touching disk or SQLite."""
    return [
        {"data": image.getvalue(), "original_name": image.name}
        for image in (uploads or [])
    ]


def _simulate_demo_workflow(product):
    """Create conspicuously simulated sample content in session memory only."""
    price = calculate_pricing({
        "manufacturing_cost": product["manufacturing_cost"],
        "packaging_cost": product["packaging_cost"],
        "shipping_cost": product["shipping_cost"],
        "other_fixed_fees": product["fixed_marketplace_fees"],
        "commission_rate": product["commission_rate"],
        "desired_profit_margin": product["desired_profit_margin"],
    })
    sample_title = f"{product['name']} | {product['category']}"
    description = {
        "seo_title": sample_title,
        "detailed_description": f"SIMULATED DEMO COPY: {product['description']} Seller specifications: {product['specifications']}.",
        "selling_points": [
            "SIMULATED: Seller-specified material and colour",
            "SIMULATED: Designed for everyday carry",
            "SIMULATED: Compact storage concept",
            "SIMULATED: Gift-ready positioning concept",
            "SIMULATED: Audience based on seller-provided details",
        ],
        "keywords": ["SIMULATED: leather wallet", "SIMULATED: handmade accessory", "SIMULATED: men's wallet"],
    }
    listing = {
        "title": sample_title,
        "description": description["detailed_description"],
        "features": description["selling_points"],
        "category": product["category"],
        "price": str(price.recommended_selling_price),
        "sku": product["sku"],
        "attributes": [{"name": "Material", "value": "SIMULATED: Leather"}, {"name": "Colour", "value": "SIMULATED: Brown"}],
        "status": "preview_only",
    }
    return {
        "workflow_id": "SIMULATED — session only",
        "product_id": DEMO_PRODUCT_ID,
        "status": "simulated",
        "is_demo": True,
        "created_at": "This simulated run is not saved to SQLite",
        "product_analysis": {
            "category": product["category"],
            "features": ["SIMULATED: Handmade leather", "SIMULATED: Brown finish"],
            "target_audience": "SIMULATED: Men (from seller input)",
            "attributes": [{"name": "Material", "value": "SIMULATED: Leather"}, {"name": "Colour", "value": "SIMULATED: Brown"}],
            "uncertain_details": ["Sample demonstration output; not produced by Gemini."],
        },
        "description": description,
        "pricing": price.model_dump(mode="json"),
        "marketing": {
            "captions": ["SIMULATED: Carry the essentials with a handmade leather wallet."],
            "hashtags": ["#SIMULATED", "#DemoSample", "#MarketPilotDemo"],
            "channels": ["SIMULATED: Instagram", "SIMULATED: Facebook"],
        },
        "marketplace_previews": {"amazon": dict(listing), "flipkart": dict(listing)},
        "marketing_overrides": None,
        "marketplace_overrides": None,
        "marketplace_review_status": "unreviewed",
        "errors": [],
    }


def _get_products():
    return list_products(get_settings().database_path)


def _select_product(label: str = "Select a product", key: str = "product_select"):
    products = _get_products()
    choices = [DEMO_PRODUCT_ID] if st.session_state.get("demo_mode") else [int(product["id"]) for product in products]
    if not choices:
        st.info("No products are saved yet. Use Add Product to create one.")
        return None
    selected_id = st.session_state.get("selected_product_id")
    index = choices.index(selected_id) if selected_id in choices else 0
    product_id = st.selectbox(
        label,
        choices,
        index=index,
        key=key,
        format_func=lambda value: "DEMO · Sample wallet (session only)" if value == DEMO_PRODUCT_ID else next(
            f"#{row['id']} · {row['name']}" for row in products if row["id"] == value
        ),
    )
    st.session_state["selected_product_id"] = product_id
    if product_id == DEMO_PRODUCT_ID:
        return _demo_product()
    return get_product(product_id, get_settings().database_path)


def _latest_workflow(product_id):
    if product_id == DEMO_PRODUCT_ID:
        return st.session_state.get("demo_workflow")
    workflows = list_product_workflows(product_id, get_settings().database_path)
    return workflows[0] if workflows else None


def _show_workflow_error(workflow):
    errors = workflow.get("errors", []) if workflow else []
    if not errors:
        return
    for error in errors:
        st.warning(error.get("message", "The step did not complete."), title=AGENT_LABELS.get(error.get("agent"), "Workflow issue"))


def _show_agent_statuses(workflow=None, active=None, container=None):
    statuses = agent_statuses(workflow, active)
    target = container if container is not None else st.container()
    with target:
        st.markdown("#### Agent execution status")
        for start in (0, 3):
            keys = list(AGENT_LABELS)[start:start + (3 if start == 0 else 2)]
            columns = st.columns(len(keys))
            for column, key in zip(columns, keys):
                state = statuses[key]
                display = "Simulated" if state == "simulated" else state.title()
                with column.container(border=True, height="stretch"):
                    st.markdown(f"**{AGENT_LABELS[key]}**")
                    badge_color = {"completed": "green", "simulated": "orange", "running": "blue", "failed": "red", "pending": "gray"}.get(state, "gray")
                    badge_icon = {"completed": ":material/check_circle:", "simulated": ":material/science:", "running": ":material/progress_activity:", "failed": ":material/error:", "pending": ":material/schedule:"}.get(state, ":material/schedule:")
                    st.badge(display, icon=badge_icon, color=badge_color)


def _display_demo_notice():
    st.warning(
        "DEMO MODE · Sample product content and simulated AI results are shown separately from live Gemini data. Nothing from this sample is written to SQLite.",
        icon=":material/science:",
    )


def _show_description(description):
    st.subheader("Generated description")
    st.markdown(f"**SEO title**  \n{description['seo_title']}")
    st.write(description["detailed_description"])
    st.markdown("**Selling points**")
    for point in description.get("selling_points", []):
        st.markdown(f"- {point}")
    st.markdown("**Keywords**")
    st.write(", ".join(description.get("keywords", [])))


def _show_analysis(analysis):
    st.subheader("Product analysis")
    st.write(f"**Category:** {analysis.get('category', 'Unknown')}")
    st.write(f"**Target audience:** {analysis.get('target_audience', 'Not available')}")
    st.markdown("**Supported features**")
    for feature in analysis.get("features", []):
        st.markdown(f"- {feature}")
    attributes = analysis.get("attributes", [])
    if attributes:
        st.dataframe(attributes, hide_index=True, width="stretch", alt="Product attributes from the analysis")
    if analysis.get("uncertain_details"):
        st.caption("Unconfirmed details: " + "; ".join(analysis["uncertain_details"]))


def _format_money(value):
    return f"{Decimal(str(value)):,.2f}"


def _show_pricing(result):
    cols = st.columns(4)
    cols[0].metric("Recommended price", f"₹{_format_money(result.recommended_selling_price)}", border=True)
    cols[1].metric("Commission", f"₹{_format_money(result.marketplace_commission)}", border=True)
    cols[2].metric("Total expenses", f"₹{_format_money(result.total_expenses)}", border=True)
    cols[3].metric("Estimated profit", f"₹{_format_money(result.estimated_profit)}", border=True)
    st.caption(f"Profit margin: {float(result.profit_margin) * 100:.2f}% · Fixed costs: ₹{_format_money(result.fixed_cost)}")


def render_dashboard():
    st.title("MarketPilot AI", icon=":material/rocket_launch:")
    st.subheader("One Product. Multiple Marketplaces. Intelligent Growth.")
    st.write("An AI-powered multi-agent platform that automates product analysis, pricing intelligence, marketplace listing preparation and digital marketing.")
    st.caption("Your local seller workspace · All dashboard metrics below come from SQLite records.")
    products = _get_products()
    workflows = [workflow for product in products for workflow in list_product_workflows(product["id"], get_settings().database_path)]
    metrics = dashboard_metrics(products, workflows)
    with st.container(horizontal=True, gap="medium"):
        st.metric("Total products", metrics["products"], border=True, height="stretch")
        st.metric("Successfully completed workflows", metrics["completed"], border=True, height="stretch")
        st.metric("Marketplace previews generated", metrics["marketplace_previews"], border=True, height="stretch")
        st.metric("Workflows needing attention", metrics["attention"], border=True, height="stretch")
    if workflows:
        latest = max(workflows, key=lambda item: (item.get("created_at", ""), item.get("workflow_id", "")))
        with st.container(border=True):
            st.markdown("### Latest workflow run")
            st.caption(f"Saved status: {latest['status'].title()} · Started {latest.get('created_at', 'unknown')}")
            _show_agent_statuses(latest)
            _show_workflow_error(latest)
    chart_col, category_col = st.columns(2)
    with chart_col.container(border=True, height="stretch"):
        st.markdown("### Workflow activity")
        if workflows:
            by_day = {}
            for workflow in workflows:
                day = (workflow.get("created_at") or "Unknown date")[:10]
                bucket = by_day.setdefault(day, {"Date": day, "Completed": 0, "Partial": 0, "Failed": 0, "Running": 0})
                state = workflow.get("status", "failed").title()
                bucket[state] = bucket.get(state, 0) + 1
            st.bar_chart(list(by_day.values()), x="Date", y=["Completed", "Partial", "Failed", "Running"], alt="Workflow attempts grouped by saved status and date")
        else:
            st.info("Workflow chart appears after a workflow attempt is saved.")
    with category_col.container(border=True, height="stretch"):
        st.markdown("### Product categories")
        category_counts = {}
        for product in products:
            category = product.get("category") or "Uncategorized"
            category_counts[category] = category_counts.get(category, 0) + 1
        if category_counts:
            st.bar_chart([{"Category": key, "Products": value} for key, value in category_counts.items()], x="Category", y="Products", alt="Product count by saved category")
        else:
            st.info("Category chart appears after products are saved.")
    st.subheader("Recent products")
    if products:
        st.dataframe(
            [{"ID": row["id"], "Product": row["name"], "Category": row["category"], "Created": row["created_at"]} for row in products[:8]],
            hide_index=True,
            width="stretch",
            alt="Recently saved products from SQLite",
        )
    else:
        st.info("No products yet. Add a product to get started.")
    if st.session_state.get("demo_mode"):
        _display_demo_notice()


def render_add_product():
    st.title("Add product", icon=":material/add_box:")
    st.caption("Save seller-provided details and up to five product images.")
    demo = st.session_state.get("demo_mode", False)
    if demo:
        _display_demo_notice()
    with st.form("add_product_form", clear_on_submit=False):
        name = st.text_input("Product name", value="Handmade Leather Wallet" if demo else "")
        category = st.text_input("Category", value="Fashion" if demo else "")
        description = st.text_area(
            "Description",
            value=("DEMO SAMPLE DATA. Handmade brown leather wallet intended for men." if demo else ""),
        )
        specifications = st.text_area(
            "Specifications",
            value=("Material: Leather\nColour: Brown\nTarget audience: Men" if demo else ""),
            help="Enter facts supplied by the seller. These will be stored as written.",
        )
        col_a, col_b = st.columns(2)
        manufacturing_cost = col_a.number_input("Manufacturing cost (₹)", min_value=0.0, value=350.0 if demo else 0.0, step=1.0)
        packaging_cost = col_b.number_input("Packaging cost (₹)", min_value=0.0, value=15.0 if demo else 0.0, step=1.0)
        shipping_cost = col_a.number_input("Shipping cost (₹)", min_value=0.0, value=40.0 if demo else 0.0, step=1.0)
        marketplace_fees = col_b.number_input("Marketplace fixed fees (₹)", min_value=0.0, value=10.0 if demo else 0.0, step=1.0)
        commission_percent = col_a.number_input("Marketplace commission (%)", min_value=0.0, max_value=99.0, value=10.0 if demo else 0.0, step=0.5)
        desired_margin_percent = col_b.number_input("Desired profit margin (%)", min_value=0.0, max_value=99.0, value=25.0 if demo else 0.0, step=0.5)
        sku = st.text_input("SKU (optional)", value="DEMO-WALLET-001" if demo else "")
        uploads = st.file_uploader(
            "Product images (JPG, PNG or WebP; up to 5, 5 MB each)",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            max_upload_size=5,
            key="add_product_images",
        )
        submitted = st.form_submit_button("Save product", type="primary", width="stretch", key="save_product")
    if demo and uploads:
        st.caption("Demo image preview · held only in this browser session; not sent to Gemini or saved to disk.")
        st.image([image.getvalue() for image in uploads], caption=[image.name for image in uploads], alt="Session-only demo product images")
    if submitted:
        if len(uploads or []) > 5:
            st.error("A product can have at most five images.")
            return
        if demo:
            st.session_state["demo_product"] = {
                "name": name,
                "category": category,
                "description": description,
                "specifications": specifications,
                "manufacturing_cost": manufacturing_cost,
                "packaging_cost": packaging_cost,
                "shipping_cost": shipping_cost,
                "fixed_marketplace_fees": marketplace_fees,
                "commission_rate": commission_percent / 100,
                "desired_profit_margin": desired_margin_percent / 100,
                "sku": sku,
                "images": _capture_demo_images(uploads),
            }
            st.session_state.pop("demo_workflow", None)
            st.success("Sample product and images saved in this browser session only. SQLite was not changed.")
            return
        try:
            product_id = create_product(
                {
                    "name": name,
                    "category": category,
                    "description": description,
                    "specifications": specifications,
                    "manufacturing_cost": manufacturing_cost,
                    "packaging_cost": packaging_cost,
                    "shipping_cost": shipping_cost,
                    "fixed_marketplace_fees": marketplace_fees,
                    "commission_rate": commission_percent / 100,
                    "desired_profit_margin": desired_margin_percent / 100,
                    "sku": sku,
                },
                get_settings().database_path,
            )
            try:
                for image in uploads or []:
                    save_product_image(product_id, image, get_settings().database_path)
            except Exception:
                delete_product(product_id, get_settings().database_path)
                raise
            st.session_state["selected_product_id"] = product_id
            st.success(f"Product saved with ID {product_id}.")
        except Exception as exc:
            st.error(f"Product could not be saved: {exc}")


def render_ai_studio():
    st.title("AI product studio", icon=":material/auto_awesome:")
    st.caption("Run the real Google ADK agents. Successful agent outputs are saved to SQLite.")
    product = _select_product(key="ai_product_select")
    if not product:
        return
    demo = product["id"] == DEMO_PRODUCT_ID
    if demo:
        _display_demo_notice()
    st.write(f"**Selected product:** {product['name']} · {product['category'] or 'Uncategorized'}")
    for image in product.get("images", []):
        if image.get("data"):
            st.image(image["data"], width=180, caption=f"DEMO · {image['original_name']}", alt="Session-only demo product image")
        elif image.get("path") and Path(image["path"]).is_file():
            st.image(image["path"], width=180, caption=image["original_name"], alt=f"Uploaded product image: {image['original_name']}")
    if st.button("Analyze Product", type="primary", width="stretch", key="analyze_product"):
        if demo:
            st.session_state["demo_workflow"] = _simulate_demo_workflow(product)
            st.success("Simulated sample workflow ready. No Gemini request was made and no AI result was saved.")
        else:
            status_box = st.status("Starting product workflow…", expanded=True)
            active_status = {}
            status_display = st.empty()
            _show_agent_statuses(None, active_status, status_display)

            def on_status(agent, state, message):
                agent_key = "marketplace" if agent == "marketplace_previews" else agent
                active_status[agent_key] = state
                status_box.write(f"**{AGENT_LABELS.get(agent_key, agent.replace('_', ' ').title())}** · {message}")
                _show_agent_statuses(None, active_status, status_display)
                status_box.update(
                    label=f"{AGENT_LABELS.get(agent_key, agent.replace('_', ' ').title())}: {state}",
                    state={"error": "error", "complete": "complete"}.get(state, "running"),
                    expanded=True,
                )

            try:
                report = asyncio.run(
                    run_product_workflow(
                        product["id"],
                        database_path=get_settings().database_path,
                        status_callback=on_status,
                    )
                )
                final_state = "complete" if report.status == "completed" else "error"
                status_box.update(label=f"Workflow {report.status}", state=final_state, expanded=True)
                st.session_state["last_workflow_id"] = report.workflow_id
                active_status.update(agent_statuses(get_workflow(report.workflow_id, get_settings().database_path)))
                _show_agent_statuses(get_workflow(report.workflow_id, get_settings().database_path), active_status, status_display)
                if report.status == "completed":
                    st.success("Workflow completed. Results are saved in Product History.")
                elif report.status == "partial":
                    st.warning("Workflow partially completed. Successful outputs were saved.")
                else:
                    st.error("Workflow failed. No successful output was fabricated.")
            except Exception as exc:
                status_box.update(label="Workflow could not start", state="error", expanded=True)
                st.error(f"Workflow could not start: {exc}")
    workflow = _latest_workflow(product["id"])
    _show_agent_statuses(workflow)
    if not workflow:
        st.info("No saved workflow results for this product yet.")
        return
    st.subheader("Latest workflow")
    if workflow.get("is_demo"):
        st.warning("SIMULATED OUTPUT · Example content for demonstrating the interface. These results are not from Gemini.", icon=":material/science:")
        st.write(f"Status: **Simulated** · {workflow['created_at']}")
    else:
        st.write(f"Status: **{workflow['status'].title()}** · Started: {workflow['created_at']}")
    _show_workflow_error(workflow)
    if workflow.get("product_analysis"):
        _show_analysis(workflow["product_analysis"])
    if workflow.get("description"):
        _show_description(workflow["description"])
    if workflow.get("marketing"):
        _show_marketing(workflow["marketing"])
    if not any(workflow.get(field) for field in ("product_analysis", "description", "marketing")):
        st.info("AI outputs are unavailable because the workflow did not complete those steps.")


def render_pricing():
    st.title("Pricing intelligence", icon=":material/monitoring:")
    st.caption("Financial values are calculated by the deterministic Python pricing engine, not Gemini.")
    product = _select_product(key="pricing_product_select")
    if not product:
        return
    demo = product["id"] == DEMO_PRODUCT_ID
    if demo:
        _display_demo_notice()
    st.write(f"**{product['name']}** · Cost values shown in ₹.")
    with st.form("pricing_form"):
        left, right = st.columns(2)
        manufacturing = left.number_input("Manufacturing cost (₹)", min_value=0.0, value=float(product["manufacturing_cost"]))
        packaging = right.number_input("Packaging cost (₹)", min_value=0.0, value=float(product["packaging_cost"]))
        shipping = left.number_input("Shipping cost (₹)", min_value=0.0, value=float(product["shipping_cost"]))
        fixed_fees = right.number_input("Marketplace fixed fees (₹)", min_value=0.0, value=float(product["fixed_marketplace_fees"]))
        commission_pct = left.number_input("Commission (%)", min_value=0.0, max_value=99.0, value=float(product["commission_rate"]) * 100, step=0.5)
        margin_pct = right.number_input("Desired profit margin (%)", min_value=0.0, max_value=99.0, value=float(product["desired_profit_margin"]) * 100, step=0.5)
        submitted = st.form_submit_button("Calculate and save", type="primary", width="stretch", key="calculate_pricing")
    if submitted:
        try:
            inputs = PricingInput(
                manufacturing_cost=manufacturing,
                packaging_cost=packaging,
                shipping_cost=shipping,
                other_fixed_fees=fixed_fees,
                commission_rate=commission_pct / 100,
                desired_profit_margin=margin_pct / 100,
            )
            result = calculate_pricing(inputs)
            values = {
                "manufacturing_cost": manufacturing,
                "packaging_cost": packaging,
                "shipping_cost": shipping,
                "fixed_marketplace_fees": fixed_fees,
                "commission_rate": commission_pct / 100,
                "desired_profit_margin": margin_pct / 100,
                "target_price": float(result.recommended_selling_price),
            }
            if demo:
                demo_product = dict(product)
                demo_product.update(values)
                st.session_state["demo_product"] = demo_product
            else:
                update_product(product["id"], values, get_settings().database_path)
            st.session_state["last_pricing_result"] = result.model_dump(mode="json")
            st.session_state["last_pricing_product_id"] = product["id"]
            st.success("Demo calculation updated in this session." if demo else "Pricing inputs saved to SQLite.")
        except Exception as exc:
            st.error(f"Pricing could not be calculated: {exc}")
    latest = st.session_state.get("last_pricing_result")
    if latest and st.session_state.get("last_pricing_product_id") == product["id"]:
        result = PricingResult.model_validate(latest)
    else:
        try:
            result = calculate_pricing({
                "manufacturing_cost": product["manufacturing_cost"],
                "packaging_cost": product["packaging_cost"],
                "shipping_cost": product["shipping_cost"],
                "other_fixed_fees": product["fixed_marketplace_fees"],
                "commission_rate": product["commission_rate"],
                "desired_profit_margin": product["desired_profit_margin"],
            })
        except Exception as exc:
            st.warning(f"A recommendation is unavailable until the pricing inputs are valid: {exc}", title="Check pricing inputs")
            return
    if demo:
        st.badge("SIMULATED PRODUCT INPUT · Deterministic sample calculation", icon=":material/science:", color="orange")
    st.subheader("Cost structure")
    with st.container(horizontal=True, gap="medium"):
        st.metric("Manufacturing cost", f"₹{_format_money(product['manufacturing_cost'])}", border=True)
        st.metric("Packaging cost", f"₹{_format_money(product['packaging_cost'])}", border=True)
        st.metric("Shipping cost", f"₹{_format_money(product['shipping_cost'])}", border=True)
        st.metric("Marketplace fixed fees", f"₹{_format_money(product['fixed_marketplace_fees'])}", border=True)
    st.subheader("Price recommendation")
    with st.container(horizontal=True, gap="medium"):
        st.metric("Recommended selling price", f"₹{_format_money(result.recommended_selling_price)}", border=True)
        st.metric("Marketplace commission", f"₹{_format_money(result.marketplace_commission)}", border=True)
        st.metric("Estimated profit", f"₹{_format_money(result.estimated_profit)}", border=True)
        st.metric("Profit margin", f"{float(result.profit_margin) * 100:.2f}%", border=True)
    st.caption(f"Total expenses: ₹{_format_money(result.total_expenses)} · Fixed costs: ₹{_format_money(result.fixed_cost)} · Commission rate: {float(product['commission_rate']) * 100:.2f}% · Desired margin: {float(product['desired_profit_margin']) * 100:.2f}%")


def _attrs_to_text(attributes):
    return "\n".join(f"{item.get('name', '')}: {item.get('value', '')}" for item in attributes or [])


def _parse_attributes(text):
    parsed = []
    for line in text.splitlines():
        if ":" in line:
            name, value = line.split(":", 1)
            if name.strip():
                parsed.append({"name": name.strip(), "value": value.strip()})
    return parsed


def _listing_with_overrides(listing, overrides):
    result = dict(listing)
    result.update(overrides or {})
    return result


def render_marketplace():
    st.title("Marketplace distribution", icon=":material/storefront:")
    st.caption("Review-only Amazon and Flipkart previews. This page never publishes listings.")
    product = _select_product(key="marketplace_product_select")
    if not product:
        return
    workflow = _latest_workflow(product["id"])
    if not workflow or not workflow.get("marketplace_previews"):
        st.info("Marketplace previews are unavailable until the Marketplace Agent completes successfully.")
        _show_workflow_error(workflow)
        return
    if workflow.get("is_demo"):
        _display_demo_notice()
        st.badge("SIMULATED LISTING PREVIEWS", icon=":material/science:", color="orange")
    st.warning("Preview Only – Marketplace Publishing Not Connected", icon=":material/visibility:")
    previews = workflow["marketplace_previews"]
    saved_overrides = workflow.get("marketplace_overrides") or {}
    workflow_key = str(workflow["workflow_id"]).replace(" ", "_")
    st.write(f"Review status: **{workflow.get('marketplace_review_status', 'unreviewed').title()}**")
    st.caption("Edits and approvals are saved to the selected workflow. No marketplace API is called.")
    with st.form("marketplace_review_form"):
        tabs = st.tabs(["Amazon preview", "Flipkart preview"])
        submitted_overrides = {}
        for tab, platform in zip(tabs, ("amazon", "flipkart")):
            base = previews.get(platform, {})
            override = saved_overrides.get(platform, {})
            current = _listing_with_overrides(base, override)
            with tab:
                title = st.text_input("Listing title", value=current.get("title", ""), key=f"{workflow_key}_{platform}_title")
                description = st.text_area("Listing description", value=current.get("description", ""), key=f"{workflow_key}_{platform}_description")
                features = st.text_area("Key features (one per line)", value="\n".join(current.get("features", [])), key=f"{workflow_key}_{platform}_features")
                category = st.text_input("Category", value=current.get("category", ""), key=f"{workflow_key}_{platform}_category")
                price = st.number_input("Preview price (₹)", min_value=0.0, value=float(current.get("price", 0)), key=f"{workflow_key}_{platform}_price")
                sku = st.text_input("SKU", value=current.get("sku", ""), key=f"{workflow_key}_{platform}_sku")
                attributes = st.text_area("Attributes (name: value per line)", value=_attrs_to_text(current.get("attributes", [])), key=f"{workflow_key}_{platform}_attributes")
                submitted_overrides[platform] = {
                    "title": title,
                    "description": description,
                    "features": [line.strip() for line in features.splitlines() if line.strip()],
                    "category": category,
                    "price": price,
                    "sku": sku,
                    "attributes": _parse_attributes(attributes),
                    "status": "preview_only",
                }
        approved = st.checkbox("I approve these current preview fields for my review records.", key=f"{workflow_key}_approve_preview_review")
        save_clicked = st.form_submit_button("Save preview edits", type="primary", width="stretch", key=f"{workflow_key}_save_preview_edits")
    if save_clicked:
        if workflow.get("is_demo"):
            edited_demo = dict(workflow)
            edited_demo["marketplace_review_status"] = "approved" if approved else "unreviewed"
            edited_demo["marketplace_overrides"] = submitted_overrides
            st.session_state["demo_workflow"] = edited_demo
        else:
            update_workflow(
                workflow["workflow_id"],
                marketplace_review_status="approved" if approved else "unreviewed",
                marketplace_overrides=submitted_overrides,
                database_path=get_settings().database_path,
            )
        if approved:
            st.success("Preview review saved as approved. This did not publish anything.")
        else:
            st.success("Preview edits saved for review.")
        st.rerun()
    if st.button("Reject these previews", key="reject_marketplace_previews"):
        if workflow.get("is_demo"):
            edited_demo = dict(workflow)
            edited_demo["marketplace_review_status"] = "rejected"
            st.session_state["demo_workflow"] = edited_demo
        else:
            update_workflow(
                workflow["workflow_id"],
                marketplace_review_status="rejected",
                database_path=get_settings().database_path,
            )
        st.success("Preview marked rejected. Nothing was published.")
        st.rerun()


def _show_marketing(marketing, overrides=None, *, key_prefix="marketing", editable=False):
    overrides = overrides or {}
    captions = overrides.get("captions", marketing.get("captions", []))
    hashtags = overrides.get("hashtags", marketing.get("hashtags", []))
    channels = overrides.get("channels", marketing.get("channels", []))
    if editable:
        caption_text = st.text_area("Social media captions", value="\n".join(captions), key=f"{key_prefix}_captions", height=140)
        hashtag_text = st.text_area("Hashtags", value=" ".join(hashtags), key=f"{key_prefix}_hashtags", height=80)
        channel_text = st.text_input("Recommended channels", value=", ".join(channels), key=f"{key_prefix}_channels")
        result = {
            "captions": [line.strip() for line in caption_text.splitlines() if line.strip()],
            "hashtags": [item for item in hashtag_text.split() if item],
            "channels": [item.strip() for item in channel_text.split(",") if item.strip()],
        }
    else:
        st.markdown("**Social media captions**")
        st.write("\n\n".join(captions) or "No captions generated.")
        st.markdown("**Hashtags**")
        st.write(" ".join(hashtags) or "No hashtags generated.")
        st.markdown("**Recommended channels**")
        st.write(", ".join(channels) or "No channels recommended.")
        result = {"captions": captions, "hashtags": hashtags, "channels": channels}
    st.markdown("**Copy-ready campaign content**")
    st.code("\n\n".join(["\n".join(result["captions"]), " ".join(result["hashtags"])]).strip(), language=None)
    return result


def render_marketing():
    st.title("Marketing center", icon=":material/campaign:")
    st.caption("Review, edit, save, and copy Marketing Agent content.")
    product = _select_product(key="marketing_product_select")
    if not product:
        return
    workflow = _latest_workflow(product["id"])
    if not workflow or not workflow.get("marketing"):
        st.info("Marketing content is unavailable. It will appear here only after the Marketing Agent succeeds.")
        _show_workflow_error(workflow)
        return
    if workflow.get("is_demo"):
        _display_demo_notice()
        st.badge("SIMULATED CAMPAIGN CONTENT", icon=":material/science:", color="orange")
    workflow_key = str(workflow["workflow_id"]).replace(" ", "_")
    edited = _show_marketing(
        workflow["marketing"], workflow.get("marketing_overrides"),
        key_prefix=f"marketing_{workflow_key}", editable=True,
    )
    saved = st.button("Save marketing edits", type="primary", width="stretch", key=f"save_marketing_{workflow_key}")
    if saved:
        if workflow.get("is_demo"):
            edited_demo = dict(workflow)
            edited_demo["marketing_overrides"] = edited
            st.session_state["demo_workflow"] = edited_demo
        else:
            update_workflow(workflow["workflow_id"], marketing_overrides=edited, database_path=get_settings().database_path)
        st.success("Marketing edits saved." if not workflow.get("is_demo") else "Simulated demo edits saved in this session only.")
        st.rerun()


def render_product_history():
    st.title("Product history", icon=":material/history:")
    product = _select_product(key="history_product_select")
    if not product:
        return
    demo = product["id"] == DEMO_PRODUCT_ID
    if demo:
        _display_demo_notice()
        st.badge("SAMPLE PRODUCT · NOT IN SQLITE", icon=":material/science:", color="orange")
    st.subheader(product["name"])
    st.write(product.get("description") or "No seller description saved.")
    info_cols = st.columns(3)
    info_cols[0].metric("Category", product.get("category") or "Uncategorized", border=True)
    info_cols[1].metric("Created", product.get("created_at", "Unknown"), border=True)
    info_cols[2].metric("SKU", product.get("sku") or "Not set", border=True)
    if product.get("specifications"):
        st.markdown("**Seller specifications**")
        st.code(product["specifications"], language=None)
    if product.get("images"):
        image_cols = st.columns(min(5, len(product["images"])))
        for idx, image in enumerate(product["images"]):
            if image.get("data"):
                image_cols[idx % len(image_cols)].image(image["data"], caption=f"DEMO · {image['original_name']}", width=140, alt="Session-only demo product image")
            elif image.get("path") and Path(image["path"]).is_file():
                image_cols[idx % len(image_cols)].image(image["path"], caption=image["original_name"], width=140, alt=f"Uploaded product image: {image['original_name']}")
    if demo:
        workflow = _latest_workflow(product["id"])
        st.subheader("Session demo activity")
        if not workflow:
            st.info("No simulated run in this session. Use AI Product Studio and select Analyze Product to stage the sample workflow.")
        else:
            st.warning("SIMULATED WORKFLOW · This sample attempt is not stored in SQLite and is not a real Gemini result.", icon=":material/science:")
            _show_agent_statuses(workflow)
            for field, heading, renderer in (
                ("product_analysis", "Product analysis · simulated", _show_analysis),
                ("description", "Description · simulated", _show_description),
                ("marketing", "Marketing · simulated", _show_marketing),
            ):
                if workflow.get(field):
                    with st.expander(heading):
                        renderer(workflow[field])
            if workflow.get("pricing"):
                with st.expander("Pricing · deterministic sample calculation"):
                    _show_pricing(PricingResult.model_validate(workflow["pricing"]))
            if workflow.get("marketplace_previews"):
                with st.expander("Marketplace previews · simulated, preview only"):
                    st.json(workflow["marketplace_previews"])
        return
    workflows = list_product_workflows(product["id"], get_settings().database_path)
    st.subheader("Workflow runs")
    if workflows:
        st.dataframe(
            [{"Workflow": item["workflow_id"], "Status": item["status"], "Created": item["created_at"], "Marketplace review": item.get("marketplace_review_status", "unreviewed")} for item in workflows],
            hide_index=True,
            width="stretch",
            alt="Saved workflow attempts for this product",
        )
        selected_workflow = st.selectbox("Inspect saved workflow", workflows, format_func=lambda item: f"{item['created_at']} · {item['status']} · {item['workflow_id']}", key="history_workflow_select")
        _show_agent_statuses(selected_workflow)
        _show_workflow_error(selected_workflow)
        for field, title in (("product_analysis", "Product analysis"), ("description", "Description"), ("pricing", "Pricing"), ("marketing", "Marketing"), ("marketplace_previews", "Marketplace previews")):
            value = selected_workflow.get(field)
            if value:
                with st.expander(title):
                    if field == "product_analysis":
                        _show_analysis(value)
                    elif field == "description":
                        _show_description(value)
                    elif field == "marketing":
                        _show_marketing(value, selected_workflow.get("marketing_overrides"), key_prefix=f"history_{selected_workflow['workflow_id']}")
                    elif field == "pricing":
                        _show_pricing(PricingResult.model_validate(value))
                    else:
                        st.json(value)
    else:
        st.info("No workflow runs are saved for this product.")
    st.divider()
    st.subheader("Delete product")
    confirm = st.checkbox("I understand this also removes the product's locally stored images.", key="confirm_delete_product")
    if st.button("Delete this product", disabled=not confirm, type="secondary", key="delete_product"):
        if delete_product(product["id"], get_settings().database_path):
            st.session_state.pop("selected_product_id", None)
            st.success("Product, associated images, and workflow history deleted.")
            st.rerun()
        else:
            st.error("Product could not be found.")


def main():
    st.set_page_config(page_title="MarketPilot AI", page_icon=":material/rocket_launch:", layout="wide")
    initialize_database(get_settings().database_path)
    with st.sidebar:
        st.title("MarketPilot AI", icon=":material/rocket_launch:")
        st.caption("One Product. Multiple Marketplaces. Intelligent Growth.")
        st.toggle("Demo mode", key="demo_mode", value=False, help="Use session-only sample product and visibly simulated content. No Gemini calls or database writes for demo data.")
    pages = [
        st.Page(render_dashboard, title=label, icon=icon, url_path=url, help=help_text, default=(index == 0))
        for index, (label, icon, url, help_text) in enumerate(NAVIGATION)
    ]
    selected = st.navigation(pages, position="sidebar", expanded=True)
    selected.run()


if __name__ == "__main__":
    main()

