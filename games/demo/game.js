const canvas = document.querySelector("canvas");
const ctx = canvas.getContext("2d");
const coasts = ["Salt Cove", "Aster Bay", "Moon Pier", "Copper Reef"];
let turn;
let busy = false;

function draw() {
  ctx.fillStyle = ["#152b42", "#204459", "#40385d", "#243a49"][turn % 4];
  ctx.fillRect(0, 0, 390, 640);
  ctx.fillStyle = "#f2dfb8";
  ctx.font = "20px Georgia";
  ctx.fillText("LANTERN COAST", 28, 68);
  ctx.font = "34px Georgia";
  ctx.fillText(coasts[turn % 4], 28, 148);
  ctx.font = "16px sans-serif";
  ctx.fillText("Beacons lit: " + turn, 30, 192);
  ctx.fillText("Choose a signal to chart your next cove.", 30, 236);
  for (const [x, text] of [[28, "East signal"], [208, "West signal"]]) {
    ctx.fillStyle = "#ffc569";
    ctx.fillRect(x, 350, 154, 74);
    ctx.fillStyle = "#172d3c";
    ctx.fillText(text, x + 25, 395);
  }
}

async function start() {
  const r = await fetch("/session");
  turn = (await r.json()).revision;
  draw();
}
canvas.addEventListener("click", async event => {
  const r = canvas.getBoundingClientRect();
  const x = (event.clientX-r.left)*390/r.width;
  const y = (event.clientY-r.top)*640/r.height;
  if (busy || y < 350 || y > 424 || !((x>=28 && x<=182)||(x>=208 && x<=362))) return;
  busy = true;
  try {
    const response = await fetch("/signal", {method:"POST", body:JSON.stringify({revision:turn})});
    if (!response.ok) throw Error("Signal could not be saved");
    turn = (await response.json()).revision;
    draw();
  } finally { busy = false; }
});
start();

