//! Compile the actual new command modules against an explicitly selected cached engine.
//! This checks handlers over the real kernel, not a rebuilt registry, desktop or MCP server.
pub use solidcraft_engine::cmd::CommandSpec;
pub use solidcraft_engine::{EngineError, Result, Session, checked, frames, params, schema};

#[path = "../../crates/engine/src/cmd/workshop_hardware.rs"]
mod workshop_hardware;
#[path = "../../crates/engine/src/cmd/workshop_wood.rs"]
mod workshop_wood;

#[cfg(test)]
mod qualification {
    use super::*;
    use serde_json::{Value, json};
    use std::path::{Path, PathBuf};

    fn preview_directory() -> PathBuf {
        std::env::current_dir().unwrap().join("target/workshop/design-qualification/preview")
    }

    fn save_and_reopen(session: &mut Session, directory: &Path, name: &str, expected_bodies: usize) -> Session {
        let path = directory.join(name);
        session.execute("file.save", &json!({"path":path})).unwrap();
        let mut reopened = Session::default();
        reopened.execute("doc.open", &json!({"path":path})).unwrap();
        assert_eq!(reopened.model.state().bodies.len(), expected_bodies, "{name}");
        reopened
    }

    fn add_board(session: &mut Session, name: &str, z: f64) {
        session.execute("wood.board", &json!({"name":name,"material":"pine","length_mm":300,"width_mm":100,"thickness_mm":18})).unwrap();
        session.execute("solid.scale", &json!({"bodies":[format!("{name} stock")],"factors":[1.5,1,1],"origin":[0,0,0]})).unwrap();
        if z != 0.0 {
            session.execute("solid.move", &json!({"bodies":[format!("{name} stock")],"translate":[0,0,z]})).unwrap();
        }
    }

    fn hardware(session: &mut Session, template: &str, name: &str) -> Value {
        let (_nested, _) = frames::Nested::enter("furniture.insert");
        workshop_hardware::insert(
            session,
            &json!({"name":name,"template":template,
            "length_mm":if template=="butt_hinge" {60} else {400},
            "width_mm":if template=="butt_hinge" {40} else {20},
            "thickness_mm":if template=="butt_hinge" {2} else {10}}),
        )
        .unwrap()
    }

    #[test]
    fn edited_boards_joinery_hardware_and_pla_roundtrip_as_native_designs() {
        let directory = preview_directory();
        std::fs::create_dir_all(&directory).unwrap();
        let mut wood = Session::default();
        add_board(&mut wood, "Lower board", 0.0);
        add_board(&mut wood, "Upper board", 18.0);
        let cut_list = workshop_wood::cut_list(&mut wood, &json!({})).unwrap();
        assert_eq!(cut_list["total_quantity"], 2);
        for row in cut_list["rows"].as_array().unwrap() {
            assert_eq!(row["length_mm"], 450.0, "cut list must follow the edited solids");
        }
        {
            let (_nested, _) = frames::Nested::enter("wood.joinery");
            workshop_wood::joinery(
                &mut wood,
                &json!({"bodies":["Lower board stock","Upper board stock"],
                "diameter_mm":6,"clearance_mm":0.2,"depths_mm":[8,8],"count":2}),
            )
            .unwrap();
        }
        let mut reopened = save_and_reopen(&mut wood, &directory, "wood-dowels.sc", 2);
        assert_eq!(workshop_wood::cut_list(&mut reopened, &json!({})).unwrap()["total_quantity"], 2);

        let mut hinge = Session::default();
        hardware(&mut hinge, "butt_hinge", "Generic hinge");
        let mut reopened = save_and_reopen(&mut hinge, &directory, "generic-hinge.sc", 2);
        assert_eq!(reopened.execute("joint.drive", &json!({"joint":"Generic hinge motion","value":45,"quiet":true})).unwrap()["moved"], true);

        let mut slide = Session::default();
        hardware(&mut slide, "drawer_slide", "Generic slide");
        let mut reopened = save_and_reopen(&mut slide, &directory, "generic-slide.sc", 2);
        assert_eq!(reopened.execute("joint.drive", &json!({"joint":"Generic slide motion","value":100,"quiet":true})).unwrap()["moved"], true);

        let mut pla = Session::default();
        pla.execute(
            "print.part",
            &json!({"name":"PLA plate","template":"mounting_plate", "length_mm":60,
            "width_mm":30,"thickness_mm":6,"hole_diameter_mm":4.5}),
        )
        .unwrap();
        let mut reopened = save_and_reopen(&mut pla, &directory, "pla-plate.sc", 1);
        let report = reopened.execute("print.check", &json!({"bodies":["PLA plate PLA"]})).unwrap();
        assert_eq!(report["ready_for_slicer"], true);
        assert!(report["printable"].is_null());
        let measured = reopened.execute("inspect.measure", &json!({"bodies":["PLA plate PLA"]})).unwrap();
        assert_eq!(measured["bodies"][0]["material"], "Workshop PLA");
        std::fs::write(directory.join("cut-list.json"), serde_json::to_vec_pretty(&cut_list).unwrap()).unwrap();
        std::fs::write(directory.join("pla-preflight.json"), serde_json::to_vec_pretty(&report).unwrap()).unwrap();
    }
}
