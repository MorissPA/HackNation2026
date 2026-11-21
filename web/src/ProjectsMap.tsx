import { useEffect, useMemo, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { Row } from "./api";
import { mln } from "./ui";

interface ProjectsMapProps {
  projects: Row[];
  selectedGmina: string;
  onSelectGmina: (gmina: string) => void;
  onSelectProject: (id: string) => void;
  selectedPid: string | null;
}

interface GminaGroup {
  gmina: string;
  city: string;
  lat: number;
  lon: number;
  projects: Row[];
  hasOpen: boolean;
  totalValue: number;
}

export function ProjectsMap({
  projects,
  selectedGmina,
  onSelectGmina,
  onSelectProject,
  selectedPid,
}: ProjectsMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);

  // Grupowanie projektów wg gminy / współrzędnych
  const groups = useMemo(() => {
    const map = new Map<string, GminaGroup>();
    for (const p of projects) {
      if (!p.lat || !p.lon) continue;
      const key = `${p.lat.toFixed(4)},${p.lon.toFixed(4)}`;
      const existing = map.get(key);
      const val = p.contract_value ?? p.estimated_value ?? 0;
      if (existing) {
        existing.projects.push(p);
        existing.hasOpen = existing.hasOpen || (p.n_open ?? 0) > 0 || p.review_status === "Do weryfikacji";
        existing.totalValue += val;
      } else {
        map.set(key, {
          gmina: p.gmina || p.city || "Gmina",
          city: p.city || "",
          lat: p.lat,
          lon: p.lon,
          projects: [p],
          hasOpen: (p.n_open ?? 0) > 0 || p.review_status === "Do weryfikacji",
          totalValue: val,
        });
      }
    }
    return Array.from(map.values());
  }, [projects]);

  // Inicjalizacja mapy
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      center: [52.069, 19.48],
      zoom: 6,
      minZoom: 5,
      maxZoom: 14,
      scrollWheelZoom: true,
    });

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
      maxZoom: 18,
    }).addTo(map);

    const layer = L.layerGroup().addTo(map);
    markersLayerRef.current = layer;
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
      markersLayerRef.current = null;
    };
  }, []);

  // Rysowanie markerów przy zmianie grup lub zaznaczenia
  useEffect(() => {
    const map = mapRef.current;
    const layer = markersLayerRef.current;
    if (!map || !layer) return;

    layer.clearLayers();

    for (const g of groups) {
      const isSelected = selectedGmina === g.gmina || g.projects.some((p) => p.project_id === selectedPid);
      const count = g.projects.length;

      // Kolor: pomarańczowy jeśli są otwarte sprawy/ryzyka, zielony jeśli zatwierdzone
      const color = g.hasOpen ? "#d97706" : "#15803d";
      const borderColor = isSelected ? "#0052a5" : "#ffffff";
      const borderWidth = isSelected ? 4 : 2;
      const size = isSelected ? 34 : count > 1 ? 30 : 26;

      const iconHtml = `
        <div style="
          width: ${size}px;
          height: ${size}px;
          background-color: ${color};
          border: ${borderWidth}px solid ${borderColor};
          border-radius: 50%;
          box-shadow: 0 2px 6px rgba(0,0,0,0.35)${isSelected ? ", 0 0 0 3px rgba(0,82,165,0.4)" : ""};
          display: flex;
          align-items: center;
          justify-content: center;
          color: #ffffff;
          font-weight: 800;
          font-size: ${size > 28 ? "13px" : "11px"};
          font-family: inherit;
          cursor: pointer;
          transition: transform 0.15s ease;
        " title="${g.gmina}">
          ${count > 1 ? count : "•"}
        </div>
      `;

      const customIcon = L.divIcon({
        html: iconHtml,
        className: "custom-gmina-pin",
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
        popupAnchor: [0, -size / 2 - 4],
      });

      const marker = L.marker([g.lat, g.lon], { icon: customIcon });

      // Treść okienka popup
      const popupContent = document.createElement("div");
      popupContent.className = "map-popup";
      popupContent.style.minWidth = "240px";
      popupContent.style.fontFamily = "inherit";

      const header = document.createElement("div");
      header.style.marginBottom = "8px";
      header.style.borderBottom = "1px solid #e2e8f0";
      header.style.paddingBottom = "6px";
      header.innerHTML = `
        <div style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 700;">Gmina / Miejscowość</div>
        <div style="font-size: 15px; font-weight: 800; color: #0f172a;">${g.gmina}</div>
        <div style="font-size: 12px; color: #475569; margin-top: 2px;">
          Liczba inwestycji: <b>${count}</b> · Wartość: <b>${mln(g.totalValue)}</b>
        </div>
      `;
      popupContent.appendChild(header);

      const list = document.createElement("div");
      list.style.display = "grid";
      list.style.gap = "6px";
      list.style.maxHeight = "160px";
      list.style.overflowY = "auto";
      list.style.marginBottom = "10px";

      for (const p of g.projects) {
        const item = document.createElement("div");
        item.style.padding = "4px 6px";
        item.style.borderRadius = "4px";
        item.style.background = "#f8fafc";
        item.style.border = "1px solid #e2e8f0";
        item.style.cursor = "pointer";
        item.style.fontSize = "12px";

        item.innerHTML = `
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <b style="color: #0052a5;">${p.project_id}</b>
            <span style="font-size: 11px; color: ${p.review_status === "Zatwierdzony" ? "#16a34a" : "#d97706"}; font-weight: 600;">
              ${p.review_status}
            </span>
          </div>
          <div style="color: #334155; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 220px;" title="${p.name}">
            ${p.name}
          </div>
        `;

        item.onclick = (e) => {
          e.stopPropagation();
          onSelectProject(p.project_id);
        };
        list.appendChild(item);
      }
      popupContent.appendChild(list);

      const filterBtn = document.createElement("button");
      filterBtn.className = "btn btn-primary";
      filterBtn.style.width = "100%";
      filterBtn.style.padding = "6px 10px";
      filterBtn.style.fontSize = "12px";
      filterBtn.textContent = selectedGmina === g.gmina ? "Wyświetlasz tę gminę ✓" : `Filtruj projekty z: ${g.gmina}`;
      filterBtn.onclick = () => {
        onSelectGmina(selectedGmina === g.gmina ? "ALL" : g.gmina);
        marker.closePopup();
      };
      popupContent.appendChild(filterBtn);

      marker.bindPopup(popupContent);

      marker.on("click", () => {
        onSelectGmina(g.gmina);
      });

      layer.addLayer(marker);
    }
  }, [groups, selectedGmina, selectedPid, onSelectGmina, onSelectProject]);

  // Centrowanie mapy przy zmianie wybranej gminy
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (selectedGmina && selectedGmina !== "ALL") {
      const g = groups.find((x) => x.gmina === selectedGmina);
      if (g) {
        map.flyTo([g.lat, g.lon], 10, { duration: 0.8 });
      }
    }
  }, [selectedGmina, groups]);

  return (
    <div className="map-wrapper" style={{ position: "relative" }}>
      <div
        ref={containerRef}
        style={{
          width: "100%",
          height: "380px",
          borderRadius: "var(--radius, 6px)",
          border: "1px solid var(--line, #d4dce6)",
          zIndex: 1,
        }}
      />
      <div
        className="map-legend"
        style={{
          position: "absolute",
          bottom: "12px",
          right: "12px",
          zIndex: 1000,
          background: "rgba(255, 255, 255, 0.95)",
          backdropFilter: "blur(4px)",
          padding: "6px 12px",
          borderRadius: "4px",
          border: "1px solid var(--line, #cbd5e1)",
          fontSize: "12px",
          display: "flex",
          gap: "14px",
          alignItems: "center",
          boxShadow: "0 2px 4px rgba(0,0,0,0.08)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "#15803d", display: "inline-block" }}></span>
          <span>Zatwierdzony</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
          <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "#d97706", display: "inline-block" }}></span>
          <span>Do weryfikacji / ryzyka</span>
        </div>
        <div style={{ color: "var(--muted, #64748b)" }}>
          Gminy na mapie: <b>{groups.length}</b>
        </div>
      </div>
    </div>
  );
}
