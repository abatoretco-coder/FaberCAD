use super::*;

fn board(s: &mut Session, name: &str, base: [f64; 3]) {
    s.execute("component.create", &json!({"name":name})).unwrap();
    s.execute("solid.box", &json!({"body_name":name,"corner":base,"length":300,"width":100,"height":18})).unwrap();
    s.execute(
        "component.metadata.set",
        &json!({"component":name,"properties":{
        "grain_axis":"length","stock_length_mm":"300","stock_width_mm":"100","stock_thickness_mm":"18"}}),
    )
    .unwrap();
    s.execute("component.activate", &json!({"component":"root"})).unwrap();
}

fn pair() -> Session {
    let mut s = Session::default();
    board(&mut s, "Lower", [0.0, 0.0, 0.0]);
    board(&mut s, "Upper", [0.0, 0.0, 18.0]);
    s
}

fn drilling() -> Value {
    json!({"bodies":["Lower","Upper"],"diameter_mm":6,"clearance_mm":0.2,"depths_mm":[8,8],"count":2})
}

fn run_joinery(s: &mut Session, params: &Value) -> Result<Value> {
    // Reproduce real dispatch: nested primitives do not independently remap picks.
    let (_nested, _) = crate::frames::Nested::enter("wood.joinery");
    joinery(s, params)
}

#[test]
fn paired_drilling_derives_actual_contact_and_removes_two_matching_blind_bores() {
    let mut s = pair();
    let report = run_joinery(&mut s, &drilling()).unwrap();
    assert_eq!(report["centers_mm"], json!([[100.0, 50.0, 18.0], [200.0, 50.0, 18.0]]));
    assert_eq!(report["interface"]["source"], "actual_board_brep_contact");
    let expected = 300.0 * 100.0 * 18.0 - 2.0 * std::f64::consts::PI * 3.1_f64.powi(2) * 8.0;
    for name in ["Lower", "Upper"] {
        let volume = s.model.state().body(name).unwrap().measure().unwrap().volume;
        assert!((volume - expected).abs() < 1e-3, "{name}: {volume} vs {expected}");
    }
    assert_eq!(report["dowels_inserted"], false);
}

#[test]
fn occurrence_rotation_and_translation_drill_the_actual_world_interface() {
    let mut s = pair();
    for name in ["Lower", "Upper"] {
        let component = s.doc.components.iter().find(|c| c.name == name).unwrap().id;
        let occurrence = s.doc.occurrences.iter().find(|o| o.component == component).unwrap().id;
        s.execute(
            "occurrence.move",
            &json!({"occurrence":occurrence,"space":"world",
            "matrix":[[1,0,0,500],[0,0,-1,200],[0,1,0,100],[0,0,0,1]]}),
        )
        .unwrap();
    }
    let world = s.world_state().unwrap();
    let names: Vec<_> =
        ["Lower", "Upper"].iter().map(|name| world.bodies.iter().find(|b| b.definition_name() == *name).unwrap().name.clone()).collect();
    let mut params = drilling();
    params["bodies"] = json!(names);
    let report = run_joinery(&mut s, &params).unwrap();
    assert_eq!(report["interface"]["axis"], 1);
    assert_eq!(report["interface"]["plane_mm"], 182.0);
    assert_eq!(report["centers_mm"], json!([[600.0, 182.0, 150.0], [700.0, 182.0, 150.0]]));
    let expected = 300.0 * 100.0 * 18.0 - 2.0 * std::f64::consts::PI * 3.1_f64.powi(2) * 8.0;
    for name in ["Lower", "Upper"] {
        let volume = s.model.state().body(name).unwrap().measure().unwrap().volume;
        assert!((volume - expected).abs() < 1e-3, "{name}: {volume} vs {expected}");
    }
}

#[test]
fn fake_interface_gap_and_invalid_pattern_never_change_the_design() {
    for invalid in [
        json!({"bodies":["Lower","Upper"],"diameter_mm":6,"clearance_mm":0.2,"depths_mm":[18,8]}),
        json!({"bodies":["Lower","Upper"],"diameter_mm":6,"clearance_mm":0.2,"depths_mm":[8,8],"centers_mm":[[100,50,0]]}),
        json!({"bodies":["Lower","Upper"],"diameter_mm":6,"clearance_mm":0.2,"depths_mm":[8,8],"centers_mm":[[100,50,18],[100,50,18]]}),
        json!({"bodies":["Lower","Upper"],"diameter_mm":6,"clearance_mm":0.2,"depths_mm":[8,8],"count":2,"centers_mm":[[100,50,18]]}),
    ] {
        let mut s = pair();
        let before = s.doc.clone();
        assert!(run_joinery(&mut s, &invalid).is_err(), "{invalid}");
        assert_eq!(s.doc, before);
    }
    let mut s = Session::default();
    board(&mut s, "Lower", [0.0, 0.0, 0.0]);
    board(&mut s, "Upper", [0.0, 0.0, 19.0]);
    let before = s.doc.clone();
    assert!(run_joinery(&mut s, &drilling()).is_err());
    assert_eq!(s.doc, before);
}

#[test]
fn repeated_definition_is_not_silently_drilled_everywhere() {
    let mut s = pair();
    let component = s.doc.components.iter().find(|c| c.name == "Lower").unwrap().id;
    s.execute("occurrence.copy", &json!({"component":component,"translate":[500,0,0]})).unwrap();
    let before = s.doc.clone();
    assert!(run_joinery(&mut s, &drilling()).is_err());
    assert_eq!(s.doc, before);
}

#[test]
fn cut_list_remeasures_local_geometry_counts_occurrences_and_does_not_mutate() {
    let mut s = Session::default();
    board(&mut s, "Shelf", [0.0, 0.0, 0.0]);
    s.execute("solid.scale", &json!({"bodies":["Shelf"],"factors":[2,1,1],"origin":[0,0,0]})).unwrap();
    let component = s.doc.components.iter().find(|c| c.name == "Shelf").unwrap().id;
    s.execute("occurrence.copy", &json!({"component":component,"translate":[0,0,100]})).unwrap();
    let before = s.doc.clone();
    let report = cut_list(&mut s, &json!({})).unwrap();
    assert_eq!(report["rows"][0]["length_mm"], 600.0);
    assert_eq!(report["rows"][0]["width_mm"], 100.0);
    assert_eq!(report["rows"][0]["thickness_mm"], 18.0);
    assert_eq!(report["rows"][0]["quantity"], 2);
    assert_eq!(report["total_quantity"], 2);
    assert_eq!(report["fabrication_ready"], false);
    assert_eq!(s.doc, before);
}

#[test]
fn cut_list_marks_machined_stock_as_envelope_only() {
    let mut s = pair();
    run_joinery(&mut s, &drilling()).unwrap();
    let report = cut_list(&mut s, &json!({})).unwrap();
    assert_eq!(report["rows"][0]["shape_status"], "machined_or_profiled_envelope_review_required");
    assert!(report["rows"][0]["warnings"].as_array().unwrap().len() > 0);
}
