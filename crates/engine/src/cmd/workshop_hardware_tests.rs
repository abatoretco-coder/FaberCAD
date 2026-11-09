use super::*;

fn hinge(name: &str) -> Value {
    json!({"name":name,"template":"butt_hinge","length_mm":60,"width_mm":40,"thickness_mm":2,"travel":110})
}

#[test]
fn generic_hinge_has_real_motion_and_explicit_provenance() {
    let mut s = Session::default();
    let result = insert(&mut s, &hinge("Door hinge")).unwrap();
    assert_eq!(result["components"].as_array().unwrap().len(), 2);
    assert_eq!(result["geometry_provenance"]["kind"], "envelope_proxy");
    assert_eq!(result["geometry_provenance"]["generated_from_evidence"], false);
    assert!(result["manufacturer_reference"].is_null());
    let measured = s.execute("inspect.measure", &json!({"bodies":["Door hinge fixed envelope","Door hinge moving envelope"]})).unwrap();
    assert!(measured["bodies"].as_array().unwrap().iter().all(|b| b["closed"] == true && b["volume_mm3"].as_f64().unwrap() > 0.0));
    let moved = s.execute("joint.drive", &json!({"joint":"Door hinge motion","value":90,"quiet":true})).unwrap();
    assert_eq!(moved["moved"], true);
    let limited = s.execute("joint.drive", &json!({"joint":"Door hinge motion","value":200,"quiet":true})).unwrap();
    assert_eq!(limited["values"][0]["value"], 110.0);
}

#[test]
fn slide_is_two_rails_with_a_limited_slider() {
    let mut s = Session::default();
    let result =
        insert(&mut s, &json!({"name":"Drawer","template":"drawer_slide","length_mm":400,"width_mm":20,"thickness_mm":10,"travel":300})).unwrap();
    assert_eq!(result["travel_unit"], "mm");
    let moved = s.execute("joint.drive", &json!({"joint":"Drawer motion","value":120,"quiet":true})).unwrap();
    assert_eq!(moved["moved"], true);
    let measured = s.execute("inspect.measure", &json!({"bodies":["Drawer moving envelope"]})).unwrap();
    assert!((measured["bodies"][0]["bbox"]["min"][0].as_f64().unwrap() - 120.0).abs() < 1e-6);
    let limited = s.execute("joint.drive", &json!({"joint":"Drawer motion","value":500,"quiet":true})).unwrap();
    assert_eq!(limited["values"][0]["value"], 300.0);
}

#[test]
fn invalid_hardware_inputs_never_partially_mutate_design() {
    let mut s = Session::default();
    for (key, value) in [("width_mm", json!(3)), ("travel", json!(181)), ("clearance_mm", json!(-1)), ("template", json!("invented"))] {
        let mut p = hinge("Invalid");
        p[key] = value;
        let before = s.doc.clone();
        assert!(insert(&mut s, &p).is_err());
        assert_eq!(s.doc, before);
    }
    insert(&mut s, &hinge("Existing")).unwrap();
    let before = s.doc.clone();
    assert!(insert(&mut s, &hinge("Existing")).is_err());
    assert_eq!(s.doc, before);
}

#[test]
fn direct_insert_preserves_existing_history_and_active_context() {
    let mut s = Session::default();
    s.execute("component.create", &json!({"name":"User component"})).unwrap();
    s.execute("solid.box", &json!({"length":20,"width":30,"height":4,"body_name":"User body"})).unwrap();
    let active = s.active_component;
    let path = s.active_occurrence_path.clone();
    let previous_history = s.undo.len();
    insert(&mut s, &hinge("Context hinge")).unwrap();
    assert_eq!(s.active_component, active);
    assert_eq!(s.active_occurrence_path, path);
    assert_eq!(s.undo.len(), previous_history);
    assert!(s.world_state().unwrap().body("User body").is_some());
    // The command registry's outer undo snapshot is intentionally not simulated
    // by this direct-handler qualification against the cached engine library.
}
