export default function BlockInfo({ block: b }) {
  const rows = [
    ['Estate', b.estate_name],
    ['Location', `${b.region} (${b.agro_zone}-country)`],
    ['Area', `${b.area_ha} ha`],
    ['Elevation', `${b.elevation_m} m`],
    ['Slope', `${b.slope_pct} %`],
    ['Soil', b.soil_type.replace(' (SoilGrids)', '')],
    ['Field capacity / WP', `${b.field_capacity_pct} / ${b.wilting_point_pct} %`],
    ['Cultivar', b.cultivar],
    ['Bush age', `${b.bush_age_yrs} yrs`],
    ['Shade cover', `${b.shade_tree_cover_pct} %`],
    ['Irrigation', b.irrigation_available ? 'available' : 'none'],
  ]
  return (
    <div className="card">
      <div className="card-title">Block {b.block_id}</div>
      <dl className="space-y-1.5 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2">
            <dt className="text-stone-500">{k}</dt>
            <dd className="text-right font-medium text-stone-800">{v}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-stone-400">Soil: ISRIC SoilGrids 250 m (real). Estate names are fictional.</p>
    </div>
  )
}
