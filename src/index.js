
export default {
  async fetch(request, env, ctx) {
    return new Response("SNOW ALERT Worker funguje!", {
      headers: {
        "content-type": "text/plain; charset=UTF-8"
      }
    });
  },

  async scheduled(controller, env, ctx) {
    console.log("SNOW ALERT – hodinová kontrola spuštěna");
  }
};
