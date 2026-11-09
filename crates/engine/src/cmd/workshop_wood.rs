//! Small woodworking operations derived from the actual design, not nominal stock labels.
use super::CommandSpec;
use crate::schema::{TypedContract, output_schema_for};
use crate::{Result, Session, params::bad};
use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

const JOINERY: TypedContract<JoineryParams> = TypedContract::new();
const CUT_LIST: TypedContract<CutListParams> = TypedContract::new();
const TOLERANCE: f64 = 1e-5;

#[derive(Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
struct JoineryParams {
    bodies: Vec<String>,
    #[serde(default)]
    centers_mm: Option<Vec<[f64; 3]>>,
    #[serde(default)]
    count: Option<usize>,
    diameter_mm: f64,
    clearance_mm: f64,
    depths_mm: [f64; 2],
}

#[derive(Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
struct CutListParams {}

#[derive(Serialize, JsonSchema)]
struct CutRow {
    component: String,
    component_id: u64,
    name: String,
    body: String,
    quantity: u64,
    length_mm: f64,
    width_mm: f64,
    thickness_mm: f64,
    grain_axis: String,
    grain_status: String,
    material: String,
    dimension_basis: String,
    shape_status: String,
    warnings: Vec<String>,
    cutting_allowance_mm: Option<f64>,
    kerf_mm: Option<f64>,
}

#[derive(Serialize, JsonSchema)]
struct CutListResult {
    units: String,
    rows: Vec<CutRow>,
    total_quantity: u64,
    fabrication_ready: bool,
    limitations: Vec<String>,
}

#[derive(Serialize, JsonSchema)]
struct ContactInterface {
    source: String,
    axis: usize,
    plane_mm: f64,
}

#[derive(Serialize, JsonSchema)]
struct JoineryResult {
    kind: String,
    bodies: Vec<String>,
    centers_mm: Vec<[f64; 3]>,
    hole_diameter_mm: f64,
    dowel_diameter_mm: f64,
    depths_mm: [f64; 2],
    interface: ContactInterface,
    dowels_inserted: bool,
    strength_verified: bool,
    requires_fit_sample: bool,
}

pub static COMMANDS: &[CommandSpec] = &[
    CommandSpec::new("wood.joinery", "Dowel Drilling", crate::checked!("wood.joinery", joinery))
        .icon("hole").contract(&JOINERY).output(output_schema_for::<JoineryResult>)
        .params("bodies: two touching axis-aligned rectangular workshop wood boards; diameter_mm, clearance_mm (diametral), depths_mm: [depth in first board, depth in second]; count?: 2 (1..16 evenly spaced on the actual common face) OR centers_mm?: [[x,y,z],...] in world mm. Derives the contact from actual geometry, drills matching blind holes atomically; does not insert dowels or certify the joint."),
    CommandSpec::new("wood.cut_list", "Wood Cutting List", crate::checked!("wood.cut_list", cut_list))
        .icon("bom").noundo().contract(&CUT_LIST).output(output_schema_for::<CutListResult>)
        .params("No parameters. Actual component-local wood envelopes and current BOM quantities, in mm; grain from stock metadata. Recomputed after edits. Not an optimized nesting plan, kerf allowance or manufacturing certification."),
];

/// Component properties identify intended workshop wood; dimensions always come from BRep.
fn wood_component<'a>(s: &'a Session, component: u64, command: &str) -> Result<&'a solidcraft_doc::Component> {
    let c = s.doc.components.iter().find(|c| c.id == component).ok_or_else(|| bad(command, "choose a workshop board component"))?;
    if !c.properties.contains_key("grain_axis") || !c.properties.contains_key("stock_thickness_mm") {
        return Err(bad(command, "choose a workshop wood board; imported or unlabelled bodies need explicit stock preparation"));
    }
    Ok(c)
}

fn bounds(body: &solidcraft_doc::ModelBody, command: &str) -> Result<([f64; 3], [f64; 3], f64)> {
    if body.body.is_mesh() || body.body.is_surface() {
        return Err(bad(command, "wood operations require a closed CAD solid, not a mesh or surface"));
    }
    let m = body.measure()?;
    let low = [m.bbox.min.x, m.bbox.min.y, m.bbox.min.z];
    let high = [m.bbox.max.x, m.bbox.max.y, m.bbox.max.z];
    if !m.volume.is_finite() || m.volume <= 0.0 || low.iter().chain(&high).any(|v| !v.is_finite()) || (0..3).any(|a| high[a] - low[a] <= TOLERANCE) {
        return Err(bad(command, "wood body has invalid dimensions or volume"));
    }
    Ok((low, high, m.volume))
}

pub(super) fn cut_list(s: &mut Session, params: &Value) -> Result<Value> {
    let command = "wood.cut_list";
    let _: CutListParams = serde_json::from_value(params.clone()).map_err(|e| bad(command, e.to_string()))?;
    let bom = s.execute("assembly.bom", &json!({"group_by":["definition"]}))?;
    let state = s.model.state();
    let mut rows = Vec::new();
    let mut total = 0_u64;
    let bom_rows = bom["rows"].as_array().ok_or_else(|| bad(command, "BOM rows are unavailable"))?;
    for row in bom_rows {
        let component = row["components"].get(0).and_then(Value::as_u64).ok_or_else(|| bad(command, "BOM definition is unavailable"))?;
        let Some(c) = s.doc.components.iter().find(|c| c.id == component && c.properties.contains_key("grain_axis")) else { continue };
        wood_component(s, component, command)?;
        let bodies: Vec<_> = state.bodies.iter().filter(|b| s.doc.body_component(&b.name, b.feature) == component).collect();
        let [body] = bodies.as_slice() else {
            return Err(bad(command, format!("{} must contain exactly one solid for a wood cutting-list row", c.name)));
        };
        let (low, high, volume) = bounds(body, command)?;
        let size = [0, 1, 2].map(|a| high[a] - low[a]);
        let envelope = size.iter().product::<f64>();
        let rectangular = (volume - envelope).abs() <= envelope * 1e-7;
        let quantity = row["count"].as_u64().ok_or_else(|| bad(command, "BOM quantity is unavailable"))?;
        total = total.checked_add(quantity).ok_or_else(|| bad(command, "cutting-list quantity overflow"))?;
        rows.push(CutRow {
            component: c.name.clone(),
            component_id: component,
            name: c.name.clone(),
            body: body.name.clone(),
            quantity,
            length_mm: size[0],
            width_mm: size[1],
            thickness_mm: size[2],
            grain_axis: c.properties.get("grain_axis").cloned().unwrap_or_default(),
            grain_status: "declared_stock_axis_verify_after_feature_transforms".into(),
            material: s.doc.body_material(&body.name),
            dimension_basis: "current_component_local_geometry_envelope".into(),
            shape_status: if rectangular { "rectangular_blank" } else { "machined_or_profiled_envelope_review_required" }.into(),
            warnings: vec![
                "verify actual stock, machining allowances and tenon extensions".into(),
                "grain remains the declared stock axis; recheck after feature rotations or shears".into(),
            ],
            cutting_allowance_mm: None,
            kerf_mm: None,
        });
    }
    Ok(json!(CutListResult {
        units: "mm".into(),
        rows,
        total_quantity: total,
        fabrication_ready: false,
        limitations: vec![
            "component-local envelopes; inspect rotated/profiled stock and tenon extensions".into(),
            "no kerf, machining allowance, nesting or strength validation".into(),
            "quantities follow assembly BOM inclusion rules".into()
        ]
    }))
}

pub(super) fn joinery(s: &mut Session, params: &Value) -> Result<Value> {
    let command = "wood.joinery";
    let p: JoineryParams = serde_json::from_value(params.clone()).map_err(|e| bad(command, e.to_string()))?;
    if p.bodies.len() != 2 || p.bodies[0] == p.bodies[1] || p.bodies.iter().any(|n| n.trim().is_empty()) {
        return Err(bad(command, "select two different wood boards"));
    }
    if !p.diameter_mm.is_finite()
        || p.diameter_mm <= 0.0
        || p.diameter_mm > 50.0
        || !p.clearance_mm.is_finite()
        || !(0.0..=2.0).contains(&p.clearance_mm)
        || p.depths_mm.iter().any(|d| !d.is_finite() || *d <= 0.0 || *d > 100.0)
        || p.centers_mm.is_some() && p.count.is_some()
    {
        return Err(bad(command, "give a positive dowel diameter/depth, diametral clearance 0..2 mm and centers OR count"));
    }
    let world = s.world_state()?;
    let mut boxes = Vec::new();
    let mut definitions = Vec::new();
    for name in &p.bodies {
        let body = world.body(name).ok_or_else(|| bad(command, format!("unknown board `{name}`")))?;
        let component = s.doc.body_component(body.definition_name(), body.feature);
        wood_component(s, component, command)?;
        if world.bodies.iter().filter(|b| b.definition_name() == body.definition_name()).count() != 1 {
            return Err(bad(command, "make repeated board definitions independent before drilling one placement"));
        }
        let b = bounds(body, command)?;
        let rectangular_volume = (0..3).map(|a| b.1[a] - b.0[a]).product::<f64>();
        if (b.2 - rectangular_volume).abs() > rectangular_volume * 1e-7 {
            return Err(bad(command, "initial dowel drilling requires axis-aligned rectangular boards without previous machining"));
        }
        boxes.push(b);
        definitions.push(component);
    }
    if definitions[0] == definitions[1] {
        return Err(bad(command, "boards must belong to different component definitions"));
    }
    let mut contacts = Vec::new();
    for axis in 0..3 {
        if (boxes[0].1[axis] - boxes[1].0[axis]).abs() <= TOLERANCE {
            contacts.push((axis, 1.0, boxes[0].1[axis]));
        } else if (boxes[0].0[axis] - boxes[1].1[axis]).abs() <= TOLERANCE {
            contacts.push((axis, -1.0, boxes[0].0[axis]));
        }
    }
    let [(axis, direction, plane)] = contacts.as_slice() else {
        return Err(bad(command, "boards must share one unambiguous planar butt interface; gaps and overlaps are refused"));
    };
    let (axis, direction, plane) = (*axis, *direction, *plane);
    let across: Vec<_> = (0..3).filter(|a| *a != axis).collect();
    let low = [0, 1, 2].map(|a| boxes[0].0[a].max(boxes[1].0[a]));
    let high = [0, 1, 2].map(|a| boxes[0].1[a].min(boxes[1].1[a]));
    let radius = (p.diameter_mm + p.clearance_mm) / 2.0;
    if across.iter().any(|a| high[*a] - low[*a] <= 2.0 * (radius + 1.0))
        || (0..2).any(|b| p.depths_mm[b] + 1.0 >= boxes[b].1[axis] - boxes[b].0[axis])
    {
        return Err(bad(command, "joint needs at least 1 mm edge/remaining-wall clearance and sufficient blind-hole depth"));
    }
    let centers = if let Some(centers) = p.centers_mm {
        centers
    } else {
        let count = p.count.unwrap_or(2);
        if !(1..=16).contains(&count) {
            return Err(bad(command, "dowel count must be 1..16"));
        }
        let along = if high[across[0]] - low[across[0]] >= high[across[1]] - low[across[1]] { across[0] } else { across[1] };
        (0..count)
            .map(|i| {
                let mut center = [0, 1, 2].map(|a| (low[a] + high[a]) / 2.0);
                center[axis] = plane;
                center[along] = low[along] + (high[along] - low[along]) * (i + 1) as f64 / (count + 1) as f64;
                center
            })
            .collect()
    };
    if centers.is_empty()
        || centers.len() > 16
        || centers.iter().any(|center| {
            center.iter().any(|v| !v.is_finite())
                || (center[axis] - plane).abs() > TOLERANCE
                || across.iter().any(|a| center[*a] - radius - 1.0 < low[*a] || center[*a] + radius + 1.0 > high[*a])
        })
    {
        return Err(bad(command, "hole centers must lie on both actual contact faces with a 1 mm edge margin"));
    }
    for (i, center) in centers.iter().enumerate() {
        if centers.iter().skip(i + 1).any(|other| across.iter().map(|a| (center[*a] - other[*a]).powi(2)).sum::<f64>().sqrt() < 2.0 * radius + 1.0) {
            return Err(bad(command, "dowel holes overlap or leave less than 1 mm between them"));
        }
    }
    let mut computed = s.scratch();
    computed.execute("component.activate", &json!({"component":"root"}))?;
    for (board, name) in p.bodies.iter().enumerate() {
        let sign = if board == 0 { -direction } else { direction };
        let mut bore_axis = [0.0; 3];
        bore_axis[axis] = sign;
        for center in &centers {
            let mut base = *center;
            base[axis] -= sign * 0.01;
            computed.execute(
                "solid.cylinder",
                &json!({"radius":radius,"height":p.depths_mm[board]+0.01,"base":base,
                "axis":bore_axis,"operation":"cut","targets":[name]}),
            )?;
        }
    }
    computed.undo.clear();
    computed.active_component = s.active_component;
    computed.active_occurrence_path = s.active_occurrence_path.clone();
    computed.active_sketch = s.active_sketch;
    s.accept_computed(computed);
    Ok(json!(JoineryResult {
        kind: "paired_blind_dowel_drilling".into(),
        bodies: p.bodies,
        centers_mm: centers,
        hole_diameter_mm: 2.0 * radius,
        dowel_diameter_mm: p.diameter_mm,
        depths_mm: p.depths_mm,
        interface: ContactInterface { source: "actual_board_brep_contact".into(), axis, plane_mm: plane },
        dowels_inserted: false,
        strength_verified: false,
        requires_fit_sample: true
    }))
}

#[cfg(test)]
#[path = "workshop_wood_tests.rs"]
mod tests;
