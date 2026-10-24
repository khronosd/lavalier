import { render } from "preact";
import { initToken } from "./api";
import { App } from "./app";
import { applyAppearance } from "./theme";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/day.css";
import "./styles/lists.css";

initToken();
applyAppearance("system");
render(<App />, document.getElementById("app")!);
