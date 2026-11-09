use super::*;

#[test]
fn workshop_material_accepts_selected_assembly_occurrences() {
    let mut s = Session::default();
    s.execute("wood.board", &json!({"name":"Repeated shelf","material":"pine","length_mm":600,"width_mm":300,"thickness_mm":18})).unwrap();
    let component = s.doc.components.iter().find(|c| c.name == "Repeated shelf").unwrap().id;
    let copy = s.execute("occurrence.copy", &json!({"component":component,"translate":[0,0,400]})).unwrap()["occurrence"].as_u64().unwrap();
    let world_name = s.occurrence_placement(&[copy]).unwrap().bodies[0].world.clone();
    assert_ne!(world_name, "Repeated shelf stock");
    let before = s.doc.clone();
    assert!(s.execute("workshop.material", &json!({"material":"oak","bodies":[world_name,"missing"]})).is_err());
    assert_eq!(s.doc, before);
    s.execute("workshop.material", &json!({"material":"oak","bodies":[world_name]})).unwrap();
    assert_eq!(s.execute("inspect.measure", &json!({"bodies":[world_name]})).unwrap()["bodies"][0]["material"], "Workshop Oak");
    s.execute("edit.undo", &json!({})).unwrap();
    assert_eq!(s.doc, before);
}

#[test]
fn suggested_print_orientations_respect_layer_height() {
    let mut s = Session::default();
    s.execute("solid.box", &json!({"body_name":"Thin sheet","length":60,"width":30,"height":0.05})).unwrap();
    s.execute("workshop.material", &json!({"material":"pla","bodies":["Thin sheet"]})).unwrap();
    let report = s.execute("print.check", &json!({"bodies":["Thin sheet"]})).unwrap();
    assert_eq!(report["ready_for_slicer"], false);
    let size = &report["bodies"][0]["size_mm"];
    for order in report["bodies"][0]["fitting_axis_permutations"].as_array().unwrap() {
        let z = order[2].as_u64().unwrap() as usize;
        assert!(size[z].as_f64().unwrap() + 1e-6 >= 0.2, "suggested a height below one layer: {order}");
    }
}

#[test]
fn stock_is_one_undo_step_with_material_grain_and_bom() {
    let mut s = Session::default();
    let before = s.doc.components.len();
    s.execute("wood.board", &json!({"name":"Shelf","material":"pine","length_mm":600,"width_mm":300,"thickness_mm":18,"grain":"length"})).unwrap();
    let measure = s.execute("inspect.measure", &json!({"bodies":["Shelf stock"]})).unwrap();
    assert!((measure["total"]["volume_mm3"].as_f64().unwrap() - 3240000.0).abs() < 0.01);
    let bom = s.execute("assembly.bom", &json!({})).unwrap();
    assert!(bom.to_string().contains("nominal_measure_before_cutting"));
    s.execute("edit.undo", &json!({})).unwrap();
    assert_eq!(s.doc.components.len(), before);
    assert!(s.doc.user_materials.is_empty());
    s.execute("edit.redo", &json!({})).unwrap();
    assert!(s.execute("inspect.measure", &json!({"bodies":["Shelf stock"]})).is_ok());
}

#[test]
fn printer_preflight_blocks_oversize_and_never_certifies_printability() {
    let mut s = Session::default();
    s.execute("print.part", &json!({"name":"Plate","template":"mounting_plate","length_mm":60,"width_mm":30,"thickness_mm":6,"hole_diameter_mm":4}))
        .unwrap();
    let report = s.execute("print.check", &json!({"bodies":["Plate PLA"]})).unwrap();
    assert_eq!(report["ready_for_slicer"], true);
    assert!(report["printable"].is_null());
    assert_eq!(report["bodies"][0]["wall_thickness_status"], "not_measured");
    s.execute("solid.box", &json!({"body_name":"One layer","length":20,"width":20,"height":0.2})).unwrap();
    s.execute("material.assign", &json!({"bodies":["One layer"],"material":"Workshop PLA"})).unwrap();
    assert_eq!(s.execute("print.check", &json!({"bodies":["One layer"]})).unwrap()["ready_for_slicer"], true);
    s.execute(
        "print.part",
        &json!({"name":"Oversize","template":"mounting_plate","length_mm":300,"width_mm":30,"thickness_mm":6,"hole_diameter_mm":4}),
    )
    .unwrap();
    assert_eq!(s.execute("print.check", &json!({"bodies":["Oversize PLA"]})).unwrap()["ready_for_slicer"], false);
    assert!(s.execute("print.check", &json!({"bodies":["Plate PLA"],"layer_height_mm":0.5})).is_err());
    assert!(s.execute("print.check", &json!({"bodies":[]})).is_err());
    assert!(s.execute("print.check", &json!({"bodies":["Plate PLA","Plate PLA"]})).is_err());
    s.execute("wood.board", &json!({"name":"Poplar","material":"poplar_plywood","length_mm":60,"width_mm":30,"thickness_mm":5})).unwrap();
    assert_eq!(s.execute("print.check", &json!({"bodies":["Poplar stock"]})).unwrap()["ready_for_slicer"], false);
}

#[test]
fn invalid_inputs_and_material_conflicts_leave_design_unchanged() {
    let mut s = Session::default();
    for params in [
        json!({"name":"Bad","material":"pine","length_mm":0,"width_mm":10,"thickness_mm":18}),
        json!({"name":"Bad","material":"invented","length_mm":100,"width_mm":10,"thickness_mm":18}),
    ] {
        assert!(s.execute("wood.board", &params).is_err());
        assert!(s.doc.components.is_empty());
        assert!(s.doc.user_materials.is_empty());
    }
    s.execute("material.create", &json!({"name":"Workshop Pine","density_g_cm3":9})).unwrap();
    assert!(s.execute("wood.board", &json!({"name":"Bad","material":"pine","length_mm":100,"width_mm":10,"thickness_mm":18})).is_err());
    assert!(s.doc.components.is_empty());
}
