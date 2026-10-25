import { Empty } from "../components/Empty";
import { MODEL_PRIVACY } from "../insights";

export function Insights() {
  return (
    <div class="page">
      <h1 class="page-title">Insights</h1>
      <Empty title="Insights arrive in a later release.">{MODEL_PRIVACY}</Empty>
    </div>
  );
}
