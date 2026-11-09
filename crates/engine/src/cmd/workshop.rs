//! FABER workshop: stock templates and printer-dependent geometric preflight.
//! Reuses normal features, materials, BOM metadata and slicer handoff.
use super::CommandSpec;
use crate::schema::workshop::{
    AppliedMaterial, BoardParams, Catalogue, CheckParams, Created, LibraryParams, MaterialParams, PartParams, PrintReport,
};
use crate::schema::{TypedContract, output_schema_for};
use crate::{Result, Session, params::bad};
use serde_json::{Value, json};

const LIBRARY: TypedContract<LibraryParams> = TypedContract::new();
const BOARD: TypedContract<BoardParams> = TypedContract::new();
const PART: TypedContract<PartParams> = TypedContract::new();
const CHECK: TypedContract<CheckParams> = TypedContract::new();
const MATERIAL: TypedContract<MaterialParams> = TypedContract::new();

pub static COMMANDS: &[CommandSpec] = &[
    CommandSpec::new("workshop.library", "Workshop", crate::checked!("workshop.library", library))
        .at("SOLID", "INSERT").icon("library").noundo().contract(&LIBRARY).output(output_schema_for::<Catalogue>)
        .params("Wood stock and nominal materials, existing standard hardware, procedural PLA templates and the Bambu A1 0.4 mm printer profile. In the app opens Workshop."),
    CommandSpec::new("wood.board", "Stock Board", crate::checked!("wood.board", board))
        .icon("box").contract(&BOARD).output(output_schema_for::<Created>)
        .params("name, material: workshop.library material id, length_mm, width_mm, thickness_mm; grain?: length|width. Creates an editable component with nominal stock and grain metadata. Measure actual stock before fabrication."),
    CommandSpec::new("workshop.material", "Workshop Material", crate::checked!("workshop.material", apply_material))
        .icon("material").contract(&MATERIAL).output(output_schema_for::<AppliedMaterial>)
        .params("material: workshop.library id; bodies: 1..64 names. Install and assign a nominal workshop wood or PLA material atomically; not a strength card."),
    CommandSpec::new("print.part", "PLA Template", crate::checked!("print.part", part))
        .icon("box").contract(&PART).output(output_schema_for::<Created>)
        .params("name, template: mounting_plate|spacer|angle_bracket, length_mm, width_mm, thickness_mm, hole_diameter_mm. Spacer uses length as outside diameter; width is unused. Nominal PLA, original procedural geometry."),
    CommandSpec::new("print.check", "Print Preflight", crate::checked!("print.check", check))
        .icon("inspect").noundo().contract(&CHECK).output(output_schema_for::<PrintReport>)
        .params("bodies: 1..64 names; printer?: bambu_a1_04; layer_height_mm?: 0.2; line_width_mm?: 0.42; bed_margin_mm?: 3. Exact solid/envelope preflight only; printable remains unknown until slicing and physical verification. No geometry changes."),
];

// Nominal mass estimates, not structural engineering properties or supplier stock.
const MATERIALS: &[(&str, &str, f64, &str)] = &[
    ("pine", "Workshop Pine", 0.50, "#C89E65"),
    ("spruce", "Workshop Spruce", 0.45, "#D9BE8C"),
    ("oak", "Workshop Oak", 0.70, "#AA804C"),
    ("beech", "Workshop Beech", 0.71, "#C49A74"),
    ("walnut", "Workshop Walnut", 0.64, "#65432D"),
    ("birch_plywood", "Workshop Birch Plywood", 0.68, "#CBB383"),
    ("poplar_plywood", "Workshop Poplar Plywood", 0.45, "#DFCCA1"),
    ("mdf", "Workshop MDF", 0.75, "#AB8862"),
    ("particleboard", "Workshop Particleboard", 0.65, "#B29A72"),
    ("osb", "Workshop OSB", 0.63, "#BCA06B"),
    ("pla", "Workshop PLA", 1.24, "#2F80ED"),
];

fn printer() -> Value {
    json!({"id":"bambu_a1_04", "name":"Bambu Lab A1 / 0.4 mm / PLA", "build_volume_mm":[256,256,256], "nozzle_mm":0.4,
        "default_layer_height_mm":0.2,"min_layer_height_mm":0.08,"max_layer_height_mm":0.28,"default_line_width_mm":0.42,"material":"PLA",
        "source":"https://bambulab.com/en/a1/tech-specs", "profile_status":"machine dimensions verified; process defaults are editable workshop assumptions"})
}

fn library(s: &mut Session, _p: &Value) -> Result<Value> {
    let materials: Vec<Value> = MATERIALS
        .iter()
        .map(|(id, name, density, color)| {
            json!({"id":id,"name":name,"density_g_cm3":density,"color":color,
        "density_status":"nominal_mass_estimate_not_mechanical_property","mechanical_properties":null})
        })
        .collect();
    let boards = vec![
        json!({"id":"shelf","length_mm":1200,"width_mm":300,"thickness_mm":18,"material":"pine"}),
        json!({"id":"sheet","length_mm":2440,"width_mm":1220,"thickness_mm":18,"material":"birch_plywood"}),
        json!({"id":"back_panel","length_mm":1200,"width_mm":600,"thickness_mm":5,"material":"poplar_plywood"}),
        json!({"id":"batten","length_mm":2000,"width_mm":40,"thickness_mm":27,"material":"spruce"}),
        json!({"id":"worktop","length_mm":1800,"width_mm":600,"thickness_mm":27,"material":"beech"}),
    ];
    let hardware = s.execute("parts.library", &json!({}))?;
    Ok(json!(Catalogue {
        materials,
        boards,
        printable_templates: vec!["mounting_plate".into(), "spacer".into(), "angle_bracket".into()],
        hardware,
        printer: printer()
    }))
}

fn positive(command: &str, value: f64, maximum: f64) -> Result<f64> {
    if value.is_finite() && value > 0.0 && value <= maximum {
        Ok(value)
    } else {
        Err(bad(command, format!("dimensions must be finite, above zero and at most {maximum} mm")))
    }
}

fn material(s: &mut Session, id: &str) -> Result<String> {
    let (_, name, density, color) = MATERIALS.iter().find(|m| m.0 == id).ok_or_else(|| bad("workshop", "unknown material id (workshop.library)"))?;
    if let Some(existing) = s.doc.user_materials.iter().find(|m| m.name.eq_ignore_ascii_case(name)) {
        if (existing.density - density).abs() > 1e-9 {
            return Err(bad("workshop", "workshop material name already has a different density; rename that material before inserting"));
        }
    } else {
        s.execute(
            "material.create",
            &json!({"name":name,"density_g_cm3":density,"color":color,"pbr":{"metallic":0,"roughness":0.75,"dielectric_ior":1.5}}),
        )?;
    }
    Ok(name.to_string())
}

fn finish(s: &mut Session, mut computed: Session, name: &str, body: &str, material: String, mut metadata: Value) -> Result<Value> {
    metadata["geometry_provenance"] = json!("procedural_template_not_manufacturer_cad");
    metadata["geometry_source"] = json!("FABER original workshop feature commands");
    metadata["units"] = json!("mm");
    computed.execute("material.assign", &json!({"bodies":[body],"material":material}))?;
    computed.execute(
        "component.metadata.set",
        &json!({"component":name,"part_number":name,"description":"FABER procedural workshop template","properties":metadata}),
    )?;
    computed.undo.clear();
    computed.active_component = s.active_component;
    computed.active_occurrence_path = s.active_occurrence_path.clone();
    computed.active_sketch = s.active_sketch;
    s.accept_computed(computed);
    Ok(json!(Created {
        component: name.into(),
        body: body.into(),
        material,
        geometry_provenance: "procedural_template_not_manufacturer_cad".into(),
        print_preflight: None
    }))
}

fn begin(s: &Session, name: &str) -> Result<Session> {
    let world = s.world_state()?;
    if world.body(&format!("{name} stock")).is_some() || world.body(&format!("{name} PLA")).is_some() {
        return Err(bad("workshop", "a body already uses this template name; choose another component name"));
    }
    if name.trim().is_empty() || name.chars().count() > 80 || s.doc.components.iter().any(|c| c.name == name) {
        return Err(bad("workshop", "give a unique component name of 1..80 characters"));
    }
    if s.active_sketch.is_some() {
        return Err(bad("workshop", "finish the active sketch before inserting stock"));
    }
    let mut computed = s.scratch();
    computed.execute("component.activate", &json!({"component":"root"}))?;
    computed.execute("component.create", &json!({"name":name}))?;
    Ok(computed)
}

fn board(s: &mut Session, p: &Value) -> Result<Value> {
    let p: BoardParams = serde_json::from_value(p.clone()).map_err(|e| bad("wood.board", e.to_string()))?;
    for value in [p.length_mm, p.width_mm, p.thickness_mm] {
        positive("wood.board", value, 10000.0)?;
    }
    if p.material == "pla" {
        return Err(bad("wood.board", "choose a wood material"));
    }
    let grain = p.grain.as_deref().unwrap_or("length");
    if !matches!(grain, "length" | "width") {
        return Err(bad("wood.board", "grain must be length or width"));
    }
    let mut computed = begin(s, &p.name)?;
    let mat = material(&mut computed, &p.material)?;
    let body = format!("{} stock", p.name);
    computed.execute("solid.box", &json!({"corner":[0,0,0],"length":p.length_mm,"width":p.width_mm,"height":p.thickness_mm,"body_name":body}))?;
    finish(
        s,
        computed,
        &p.name,
        &body,
        mat,
        json!({"stock_length_mm":p.length_mm.to_string(),"stock_width_mm":p.width_mm.to_string(),"stock_thickness_mm":p.thickness_mm.to_string(),"grain_axis":grain,"stock_status":"nominal_measure_before_cutting"}),
    )
}

fn apply_material(s: &mut Session, p: &Value) -> Result<Value> {
    let p: MaterialParams = serde_json::from_value(p.clone()).map_err(|e| bad("workshop.material", e.to_string()))?;
    validate_bodies("workshop.material", &p.bodies)?;
    // Viewport selections name occurrences; physical materials belong to body definitions.
    // Resolve every pick before changing anything, and assign a shared definition only once.
    let world = s.world_state()?;
    let mut definitions = std::collections::BTreeSet::new();
    for name in &p.bodies {
        let body = world.body(name).ok_or_else(|| bad("workshop.material", format!("unknown body `{name}`")))?;
        definitions.insert(body.definition_name().to_string());
    }
    let mut computed = s.scratch();
    let material = material(&mut computed, &p.material)?;
    let assigned = computed.execute("material.assign", &json!({"bodies":definitions,"material":material}))?;
    let material = assigned["material"].as_str().unwrap_or(&material).to_string();
    computed.undo.clear();
    s.accept_computed(computed);
    Ok(json!(AppliedMaterial { material, bodies: p.bodies }))
}

fn part(s: &mut Session, p: &Value) -> Result<Value> {
    let p: PartParams = serde_json::from_value(p.clone()).map_err(|e| bad("print.part", e.to_string()))?;
    for value in [p.length_mm, p.width_mm, p.thickness_mm, p.hole_diameter_mm] {
        positive("print.part", value, 1000.0)?;
    }
    if !matches!(p.template.as_str(), "mounting_plate" | "spacer" | "angle_bracket") {
        return Err(bad("print.part", "unknown printable template"));
    }
    let hole_limit = if p.template == "spacer" { p.length_mm } else { (p.length_mm / 2.0).min(p.width_mm) };
    if p.hole_diameter_mm >= hole_limit
        || (p.template == "angle_bracket" && (p.thickness_mm >= p.width_mm || p.hole_diameter_mm >= p.width_mm - p.thickness_mm))
    {
        return Err(bad("print.part", "hole must fit inside the part and bracket thickness must be smaller than its depth"));
    }
    let mut computed = begin(s, &p.name)?;
    let mat = material(&mut computed, "pla")?;
    let body = format!("{} PLA", p.name);
    if p.template == "spacer" {
        computed.execute("solid.cylinder", &json!({"radius":p.length_mm/2.0,"height":p.thickness_mm,"base":[0,0,0],"body_name":body}))?;
        computed.execute(
            "solid.cylinder",
            &json!({"radius":p.hole_diameter_mm/2.0,"height":p.thickness_mm+2.0,"base":[0,0,-1],"operation":"cut","targets":[body]}),
        )?;
    } else {
        computed.execute("solid.box", &json!({"corner":[0,0,0],"length":p.length_mm,"width":p.width_mm,"height":p.thickness_mm,"body_name":body}))?;
        for x in [p.length_mm / 4.0, p.length_mm * 0.75] {
            let y = if p.template == "angle_bracket" { (p.width_mm + p.thickness_mm) / 2.0 } else { p.width_mm / 2.0 };
            computed.execute(
                "solid.cylinder",
                &json!({"radius":p.hole_diameter_mm/2.0,"height":p.thickness_mm+2.0,"base":[x,y,-1],"operation":"cut","targets":[body]}),
            )?;
        }
        if p.template == "angle_bracket" {
            computed.execute(
                "solid.box",
                &json!({"corner":[0,0,0],"length":p.length_mm,"width":p.thickness_mm,"height":p.width_mm,"operation":"join","targets":[body]}),
            )?;
        }
    }
    let mut created = finish(
        s,
        computed,
        &p.name,
        &body,
        mat,
        json!({"template":p.template,"process":"FDM","filament":"PLA","validation":"requires_print_preflight_and_slicing","nominal_thickness_mm":p.thickness_mm.to_string()}),
    )?;
    created["print_preflight"] = check(s, &json!({"bodies":[body]}))?;
    Ok(created)
}

fn check(s: &mut Session, p: &Value) -> Result<Value> {
    let p: CheckParams = serde_json::from_value(p.clone()).map_err(|e| bad("print.check", e.to_string()))?;
    validate_bodies("print.check", &p.bodies)?;
    if p.printer.as_deref().is_some_and(|id| id != "bambu_a1_04") {
        return Err(bad("print.check", "unknown printer profile"));
    }
    let layer = positive("print.check", p.layer_height_mm.unwrap_or(0.2), 0.28)?;
    if layer < 0.08 {
        return Err(bad("print.check", "A1 0.4 mm profile layer height must be between 0.08 and 0.28 mm"));
    }
    let line = positive("print.check", p.line_width_mm.unwrap_or(0.42), 1.0)?;
    let margin = p.bed_margin_mm.unwrap_or(3.0);
    if !margin.is_finite() || !(0.0..=100.0).contains(&margin) || line < 0.2 {
        return Err(bad("print.check", "invalid bed margin or line width"));
    }
    let measured = s.execute("inspect.measure", &json!({"bodies":p.bodies}))?;
    let measured = measured["bodies"].as_array().ok_or_else(|| bad("print.check", "body measurements unavailable"))?;
    if measured.is_empty() {
        return Err(bad("print.check", "no measured bodies"));
    }
    let mut bodies = Vec::new();
    let mut ready = true;
    for body in measured {
        let mut size = [0.0; 3];
        for (axis, value) in size.iter_mut().enumerate() {
            *value = body["bbox"]["max"].get(axis).and_then(Value::as_f64).unwrap_or(0.0)
                - body["bbox"]["min"].get(axis).and_then(Value::as_f64).unwrap_or(0.0);
        }
        let mut blockers = Vec::new();
        if body["closed"] != true || body["volume_mm3"].as_f64().is_none_or(|v| v <= 0.0) {
            blockers.push("not_closed_solid");
        }
        let fits = |d: [f64; 3]| {
            d[0] <= 256.0 - 2.0 * margin + 1e-6
                && d[1] <= 256.0 - 2.0 * margin + 1e-6
                && d[2] <= 256.0 + 1e-6
                && d.iter().all(|n| n.is_finite() && *n > 0.0)
        };
        if !fits(size) {
            blockers.push("outside_build_volume_in_current_orientation");
        }
        let mut warnings = Vec::new();
        if size[0] + 1e-6 < line || size[1] + 1e-6 < line {
            warnings.push("overall_dimension_below_line_width");
        }
        if size[2] + 1e-6 < layer {
            blockers.push("height_below_layer_height");
        }
        if body["material"].as_str().is_none_or(|m| !m.split(|c: char| !c.is_ascii_alphanumeric()).any(|token| token.eq_ignore_ascii_case("pla"))) {
            blockers.push("assign_pla_material_before_preparing");
        }
        let orientations: Vec<_> = [[0, 1, 2], [1, 0, 2], [0, 2, 1], [2, 0, 1], [1, 2, 0], [2, 1, 0]]
            .into_iter()
            .filter(|order| fits([size[order[0]], size[order[1]], size[order[2]]]) && size[order[2]] + 1e-6 >= layer)
            .collect();
        ready &= blockers.is_empty();
        bodies.push(
            json!({"body":body["name"],"size_mm":size,"volume_mm3":body["volume_mm3"],"blockers":blockers,"warnings":warnings,"fitting_axis_permutations":orientations,
            "wall_thickness_status":"not_measured","supports_status":"requires_slicing","bed_placement_status":"arrange_and_verify_in_slicer"}),
        );
    }
    let mut profile = printer();
    profile["layer_height_mm"] = json!(layer);
    profile["line_width_mm"] = json!(line);
    profile["bed_margin_mm"] = json!(margin);
    Ok(json!(PrintReport {
        printer: profile,
        bodies,
        ready_for_slicer: ready,
        printable: None,
        unverified: vec![
            "minimum_wall_thickness".into(),
            "overhangs_bridges_supports_and_first_layer".into(),
            "intersections_and_combined_plate_layout".into(),
            "fit_strength_and_physical_print".into()
        ]
    }))
}

fn validate_bodies(command: &str, bodies: &[String]) -> Result<()> {
    let mut seen = std::collections::BTreeSet::new();
    if bodies.is_empty() || bodies.len() > 64 || bodies.iter().any(|name| name.trim().is_empty() || name.chars().count() > 512 || !seen.insert(name))
    {
        return Err(bad(command, "select 1..64 unique body names"));
    }
    Ok(())
}

#[cfg(test)]
#[path = "workshop_tests.rs"]
mod tests;
