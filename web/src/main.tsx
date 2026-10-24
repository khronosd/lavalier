import { render } from "preact";
import { initToken } from "./api";
import { App } from "./app";
import { applyAppearance } from "./theme";
import "./styles/tokens.css";
import "./styles/base.css";

initToken();
applyAppearance("system");
render(<App />, document.getElementById("app")!);
