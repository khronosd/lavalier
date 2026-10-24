import { render } from "preact";
import { initToken } from "./api";
import { start } from "./boot";
import { App } from "./app";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/day.css";
import "./styles/lists.css";
import "./styles/audio.css";
import "./styles/pendant.css";
import "./styles/settings.css";

initToken();
void start(() => render(<App />, document.getElementById("app")!));
