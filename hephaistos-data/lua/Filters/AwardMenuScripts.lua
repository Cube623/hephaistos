-- keepsake description box
Hephaistos.CreateScreenComponent[ShowAwardMenu] = function(params)
  return Hephaistos.MatchAll(params,
    { Name = "BlankObstacle", Group = "Combat_Menu" },
    { Name = "BlankObstacle", Group = "Combat_Menu_Additive" })
    and params.X >= 1325
  or Hephaistos.MatchAll(params, { Name = "LegendaryKeepsakeLockedButton", Group = "Combat_Menu" })
end

-- keepsakes icons
Hephaistos.CreateKeepsakeIcon[ShowAwardMenu] = function(args)
  return true
end
