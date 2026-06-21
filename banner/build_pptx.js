// Villa Atlantic banner — editable PPTX
// Banner: 120 x 40 cm = 47.244 x 15.748 inches
// Each element is a separate, movable text box / image.

const pptxgen = require("pptxgenjs");
const path = require("path");

const pres = new pptxgen();

// Custom slide size (inches)
pres.defineLayout({ name: "BANNER_120x40", width: 47.244, height: 15.748 });
pres.layout = "BANNER_120x40";

const COLOR_OCEAN = "0A4D68";
const COLOR_CORAL = "E8664D";
const COLOR_BG = "FEFDFB";

const slide = pres.addSlide();
slide.background = { color: COLOR_BG };

// 1. RENT ME (eyebrow, top)
slide.addText("RENT ME", {
  x: 2.6, y: 3.0, w: 12, h: 1.2,
  fontFace: "Space Grotesk",
  fontSize: 56,
  bold: true,
  color: COLOR_OCEAN,
  charSpacing: 30,
  align: "left",
  valign: "middle",
});

// 2. VILLA ATLANTIC (logo, big, coral, serif)
slide.addText("VILLA ATLANTIC", {
  x: 2.5, y: 4.5, w: 30, h: 5.5,
  fontFace: "Fraunces",
  fontSize: 240,
  bold: false,
  color: COLOR_CORAL,
  charSpacing: -3,
  align: "left",
  valign: "middle",
});

// 3. URL
slide.addText("www.atlanticvilla.net", {
  x: 2.6, y: 10.5, w: 18, h: 1.5,
  fontFace: "Space Grotesk",
  fontSize: 60,
  color: COLOR_OCEAN,
  charSpacing: 2,
  align: "left",
  valign: "middle",
});

// 4. WhatsApp icon (right side)
slide.addImage({
  path: path.resolve(__dirname, "whatsapp-icon.png"),
  x: 33.5, y: 6.4, w: 3, h: 3,
});

// 5. Phone number (right side, next to icon)
slide.addText("+XX XXX XXX XXX", {
  x: 36.8, y: 6.5, w: 9.5, h: 2.8,
  fontFace: "Space Grotesk",
  fontSize: 60,
  bold: true,
  color: COLOR_OCEAN,
  charSpacing: 2,
  align: "left",
  valign: "middle",
});

pres.writeFile({ fileName: path.resolve(__dirname, "banner-120x40-editable.pptx") })
  .then((f) => console.log("Saved:", f));
