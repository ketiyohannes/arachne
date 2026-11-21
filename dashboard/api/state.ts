import { forward } from "./_hub";

export const config = { runtime: "edge" };

export default (request: Request) => forward(request, "/api/state");
