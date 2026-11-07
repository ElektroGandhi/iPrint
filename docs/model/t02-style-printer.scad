// A pocket thermal printer in the style of the T02. An illustration for the docs, not a measured copy of the product.
// Sizes in mm. Build one part:  openscad -D 'part="body"' -o body.stl t02-style-printer.scad
part = "all";       // body | lid | button | led | platen | all
W = 78; D = 78; H = 36; R = 12; SEAM = 0.7; SPLIT = 17;
SLIT_Y = 14;        // paper comes out across the lid here
$fn = 64;

module rounded(w, d, h, r) {
    hull() for (x = [-w/2 + r, w/2 - r], y = [-d/2 + r, d/2 - r], z = [r, h - r])
        translate([x, y, z]) sphere(r);
}
module slab(z0, z1) { translate([-W, -D, z0]) cube([2*W, 2*D, z1 - z0]); }

module body() {
    difference() {
        rounded(W, D, H, R);
        slab(SPLIT, H + 1);
    }
    // recessed inner block visible through the seam
    intersection() { rounded(W - 3, D - 3, H - 2, R - 1.5); slab(SPLIT - 1, SPLIT + SEAM + 1); }
}
module lid() {
    difference() {
        intersection() { rounded(W, D, H, R); slab(SPLIT + SEAM, H + 1); }
        // paper slit
        translate([-30, SLIT_Y, H - 6]) cube([60, 1.6, 10]);
    }
}
module button() { translate([W/2 - 15, -D/2 + 15, H - 1.4]) cylinder(h = 1.8, r = 4.6); }
module led()    { translate([W/2 - 15, -D/2 + 26, H - 0.9]) cylinder(h = 1.1, r = 1.3); }
module platen() { translate([-30, SLIT_Y - 0.2, H - 3]) cube([60, 2, 2.6]); }

if (part == "body" || part == "all") body();
if (part == "lid" || part == "all") lid();
if (part == "button" || part == "all") button();
if (part == "led" || part == "all") led();
if (part == "platen" || part == "all") platen();
