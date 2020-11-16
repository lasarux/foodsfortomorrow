# -*- coding: utf-8 -*-

import logging
import math
from math import log10
from collections import defaultdict, namedtuple
from odoo import api, fields, models, exceptions, SUPERUSER_ID, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.date_utils import add, subtract
from odoo.tools.float_utils import float_round

_logger = logging.getLogger(__name__)

class mrp_production_schedule_custom_0(models.Model):
    
    _inherit = 'mrp.production.schedule'


    def get_production_schedule_view_state(self):
        company_id = self.env.company
        date_range = company_id._get_date_range()

        schedules_to_compute = self.env['mrp.production.schedule'].browse(self.get_impacted_schedule()) | self

        indirect_demand_trees = schedules_to_compute._get_indirect_demand_tree()
        
        indirect_demand_order = schedules_to_compute._get_indirect_demand_order(indirect_demand_trees)
        indirect_demand_qty = defaultdict(float)
        incoming_qty, incoming_qty_done = self._get_incoming_qty(date_range)
        outgoing_qty, outgoing_qty_done = self._get_outgoing_qty(date_range)
        read_fields = [
            'forecast_target_qty',
            'min_to_replenish_qty',
            'max_to_replenish_qty',
            'product_id',
        ]
        if self.env.user.has_group('stock.group_stock_multi_warehouses'):
            read_fields.append('warehouse_id')
        if self.env.user.has_group('uom.group_uom'):
            read_fields.append('product_uom_id')
        production_schedule_states = schedules_to_compute.read(read_fields)
        production_schedule_states_by_id = {mps['id']: mps for mps in production_schedule_states}
        for production_schedule in indirect_demand_order:
            # Bypass if the schedule is only used in order to compute indirect
            # demand.

            ########################################
            is_purchase = False
            is_fabricate = False
            quantity_week = 0
            moq = 0
            if(production_schedule.product_tmpl_id.route_ids):
                for route in production_schedule.product_tmpl_id.route_ids:
                    if(route.name == "Comprar"):
                        is_purchase = True
                    if(route.name == "Fabricar"):
                        is_fabricate = True
            
            if(is_purchase and production_schedule.product_tmpl_id.seller_ids):
                time_days = production_schedule.product_tmpl_id.seller_ids[0].x_studio_transit_time + production_schedule.product_tmpl_id.seller_ids[0].delay
                quantity_week = math.ceil(time_days/7)
                moq = production_schedule.product_tmpl_id.seller_ids[0].min_qty
                                
            elif(is_fabricate and production_schedule.product_tmpl_id.bom_ids):
                time_days = production_schedule.product_tmpl_id.bom_ids[-1].x_studio_lead_time
                quantity_week = math.ceil(time_days/7)
            ########################################


            rounding = production_schedule.product_id.uom_id.rounding
            lead_time = production_schedule._get_lead_times()
            production_schedule_state = production_schedule_states_by_id[production_schedule['id']]
            if production_schedule in self:
                procurement_date = add(fields.Date.today(), days=lead_time)
                precision_digits = max(0, int(-(log10(production_schedule.product_uom_id.rounding))))
                production_schedule_state['precision_digits'] = precision_digits
                production_schedule_state['forecast_ids'] = []
            indirect_demand_ratio = production_schedule._get_indirect_demand_ratio(indirect_demand_trees, schedules_to_compute)

            starting_inventory_qty = production_schedule.product_id.with_context(warehouse=production_schedule.warehouse_id.id).qty_available
            if len(date_range):
                starting_inventory_qty -= incoming_qty_done.get((date_range[0], production_schedule.product_id, production_schedule.warehouse_id), 0.0)
                starting_inventory_qty += outgoing_qty_done.get((date_range[0], production_schedule.product_id, production_schedule.warehouse_id), 0.0)

            pos = 0
            for date_start, date_stop in date_range:
                forecast_values = {}
                key = ((date_start, date_stop), production_schedule.product_id, production_schedule.warehouse_id)
                existing_forecasts = production_schedule.forecast_ids.filtered(lambda p: p.date >= date_start and p.date <= date_stop)
                if production_schedule in self:
                    forecast_values['date_start'] = date_start
                    forecast_values['date_stop'] = date_stop
                    forecast_values['incoming_qty'] = float_round(incoming_qty.get(key, 0.0) + incoming_qty_done.get(key, 0.0), precision_rounding=rounding)
                    forecast_values['outgoing_qty'] = float_round(outgoing_qty.get(key, 0.0) + outgoing_qty_done.get(key, 0.0), precision_rounding=rounding)

                forecast_values['indirect_demand_qty'] = float_round(indirect_demand_qty.get(key, 0.0), precision_rounding=rounding)
                replenish_qty_updated = False
                if existing_forecasts:
                    forecast_values['forecast_qty'] = float_round(sum(existing_forecasts.mapped('forecast_qty')), precision_rounding=rounding)
                    forecast_values['replenish_qty'] = float_round(sum(existing_forecasts.mapped('replenish_qty')), precision_rounding=rounding)

                    # Check if the to replenish quantity has been manually set or
                    # if it needs to be computed.
                    replenish_qty_updated = any(existing_forecasts.mapped('replenish_qty_updated'))
                    forecast_values['replenish_qty_updated'] = replenish_qty_updated
                else:
                    forecast_values['forecast_qty'] = 0.0

                if not replenish_qty_updated:
                    replenish_qty = production_schedule._get_replenish_qty(starting_inventory_qty - forecast_values['forecast_qty'] - forecast_values['indirect_demand_qty'])
                    forecast_values['replenish_qty'] = float_round(replenish_qty, precision_rounding=rounding)
                    forecast_values['replenish_qty_updated'] = False

                ########################################
                if(pos < quantity_week):
                    forecast_values['replenish_qty_updated'] = False
                pos = pos + 1
                if(forecast_values['replenish_qty'] > 0 and forecast_values['replenish_qty'] < moq):
                    forecast_values['replenish_qty'] = moq
                ########################################

                forecast_values['starting_inventory_qty'] = float_round(starting_inventory_qty, precision_rounding=rounding)
                forecast_values['safety_stock_qty'] = float_round(starting_inventory_qty - forecast_values['forecast_qty'] - forecast_values['indirect_demand_qty'] + forecast_values['replenish_qty'], precision_rounding=rounding)

                if production_schedule in self:
                    production_schedule_state['forecast_ids'].append(forecast_values)
                starting_inventory_qty = forecast_values['safety_stock_qty']
                # Set the indirect demand qty for children schedules.
                for (mps, ratio) in indirect_demand_ratio:
                    if not forecast_values['replenish_qty']:
                        continue
                    related_date = max(subtract(date_start, days=lead_time), fields.Date.today())
                    index = next(i for i, (dstart, dstop) in enumerate(date_range) if related_date <= dstart or (related_date >= dstart and related_date <= dstop))
                    related_key = (date_range[index], mps.product_id, mps.warehouse_id)
                    indirect_demand_qty[related_key] += ratio * forecast_values['replenish_qty']

            if production_schedule in self:
                # The state is computed after all because it needs the final
                # quantity to replenish.
                forecasts_state = production_schedule._get_forecasts_state(production_schedule_states_by_id, date_range, procurement_date)
                forecasts_state = forecasts_state[production_schedule.id]
                for index, forecast_state in enumerate(forecasts_state):

                    ########################################
                    if(index < quantity_week):
                        forecast_state['state'] = 'to_relaunch'
                    ########################################

                    production_schedule_state['forecast_ids'][index].update(forecast_state)

                # The purpose is to hide indirect demand row if the schedule do not
                # depends from another.
                has_indirect_demand = any(forecast['indirect_demand_qty'] != 0 for forecast in production_schedule_state['forecast_ids'])
                production_schedule_state['has_indirect_demand'] = has_indirect_demand
        return [p for p in production_schedule_states if p['id'] in self.ids]

    def set_replenish_qty(self, date_index, quantity):
        """ Save the replenish quantity and mark the cells as manually updated.

        params quantity: The new quantity to replenish
        params date_index: The manufacturing period
        """
        # Get the last date of current period
        self.ensure_one()
        date_start, date_stop = self.company_id._get_date_range()[date_index]
        existing_forecast = self.forecast_ids.filtered(lambda f:
            f.date >= date_start and f.date <= date_stop)

        ######################################
        if(existing_forecast):
            if(existing_forecast.production_schedule_id.product_tmpl_id.route_ids):
                for route in existing_forecast.production_schedule_id.product_tmpl_id.route_ids:
                    if(route.name == "Comprar"):
                        if(existing_forecast.production_schedule_id.product_tmpl_id.seller_ids):
                            moq = existing_forecast.production_schedule_id.product_tmpl_id.seller_ids[0].min_qty
                            if(quantity > 0 and quantity < moq):
                                quantity = existing_forecast.production_schedule_id.product_tmpl_id.seller_ids[0].min_qty
                                break
            
        ######################################

        quantity = float_round(float(quantity), precision_rounding=self.product_uom_id.rounding)
        quantity_to_add = quantity - sum(existing_forecast.mapped('replenish_qty'))
        if existing_forecast:
            new_qty = existing_forecast[0].replenish_qty + quantity_to_add
            new_qty = float_round(new_qty, precision_rounding=self.product_uom_id.rounding)
            existing_forecast[0].write({
                'replenish_qty': new_qty,
                'replenish_qty_updated': True
            })
        else:
            existing_forecast.create({
                'forecast_qty': 0,
                'date': date_stop,
                'replenish_qty': quantity,
                'replenish_qty_updated': True,
                'production_schedule_id': self.id
            })
        return True

    def _get_indirect_demand_ratio(self, indirect_demand_trees, other_mps):
        """ return the schedules in arg 'other_mps' directly linked to
        schedule self and the quantity nescessary in order to produce 1 unit of
        the product defined on the given schedule.
        """
        self.ensure_one()
        other_mps = other_mps.filtered(lambda s: s.warehouse_id == self.warehouse_id)
        related_mps = []

        def _first_matching_mps(node, ratio, related_mps):
            if node.product == self.product_id:
                ratio = 1.0
            elif ratio and node.product in other_mps.mapped('product_id'):
                related_mps.append((other_mps.filtered(lambda s: s.product_id == node.product), ratio))
                return related_mps
            for child in node.children:
                related_mps = _first_matching_mps(child, ratio * child.ratio, related_mps)
                if not ratio and related_mps:
                    return related_mps
            return related_mps

        for tree in indirect_demand_trees:
            if not related_mps:
                related_mps = _first_matching_mps(tree, False, [])
        return related_mps

        #     #######################################

        #     if(production_schedule.product_tmpl_id.route_ids):
        #         is_purchase = False
        #         is_fabricate = False
        #         for route in production_schedule.product_tmpl_id.route_ids:
        #             if(route.name == "Comprar"):
        #                 is_purchase = True
        #             if(route.name == "Fabricar"):
        #                 is_fabricate = True
                
        #         if(is_purchase):
        #             if(production_schedule.product_tmpl_id.seller_ids):
        #                 time_days = production_schedule.product_tmpl_id.seller_ids[0].x_studio_transit_time + production_schedule.product_tmpl_id.seller_ids[0].delay
        #                 quantity_week = math.ceil(time_days/7)
        #                 if(quantity_week > 0):
        #                     forecast_ids = production_schedule.forecast_ids
        #                     if(quantity_week < len(forecast_ids)):
        #                         for i in range(quantity_week):
        #                             forecast_ids[i]['state'] = 'launched'
                                
        #         elif(is_fabricate and production_schedule.product_tmpl_id.bom_ids):
        #             time_days = production_schedule.product_tmpl_id.bom_ids[-1].x_studio_lead_time
        #             quantity_week = math.ceil(time_days/7)
        #             if(quantity_week > 0):
        #                 forecast_ids = production_schedule.forecast_ids
        #                 if(quantity_week < len(forecast_ids)):
        #                     for i in range(quantity_week):
        #                         forecast_ids[i]['replenish_qty'] = 0
        #                         forecast_ids[i]['state'] = 'launched'
        #                         mrp = self.env['mrp.production.schedule'].search([('id','=',production_schedule['id'])])
        #                         mrp.set_replenish_qty(i, 0)

        #     #######################################

    # @api.model
    # def get_mps_view_state(self, domain=False):
    #     """ Return the global information about MPS and a list of production
    #     schedules values with the domain.

    #     :param domain: domain for mrp.production.schedule
    #     :return: values used by the client action in order to render the MPS.
    #         - dates: list of period name
    #         - production_schedule_ids: list of production schedules values
    #         - manufacturing_period: list of periods (days, months or years)
    #         - company_id: user current company
    #         - groups: company settings that hide/display different rows
    #     :rtype: dict
    #     """
    #     productions_schedules = self.env['mrp.production.schedule'].search(domain or [])
    #     productions_schedules_states = productions_schedules.get_production_schedule_view_state()
        
    #     ###############################################
        
    #     for production in productions_schedules_states:
    #         product_product =  self.env['product.product'].search([('id','=',production['product_id'][0])], limit=1)
    #         product_template =  product_product.product_tmpl_id
    #         if(product_template.route_ids):
    #             is_purchase = False
    #             is_fabricate = False
    #             for route in product_template.route_ids:
    #                 if(route.name == "Comprar"):
    #                     is_purchase = True
    #                 if(route.name == "Fabricar"):
    #                     is_fabricate = True
                
    #             moq = 0
    #             if(is_purchase):
    #                 if(product_template.seller_ids):
    #                     time_days = product_template.seller_ids[0].x_studio_transit_time + product_template.seller_ids[0].delay
    #                     moq = product_template.seller_ids[0].min_qty
    #                     quantity_week = math.ceil(time_days/7)
    #                     if(quantity_week > 0):
    #                         forecast_ids = production.get('forecast_ids')

    #                         for i in range(len(forecast_ids)):
    #                             if(is_purchase):# and forecast_ids[i]['replenish_qty'] > 0):
    #                                 forecast_ids[i]['replenish_qty'] = moq

    #                             if i < quantity_week:
    #                                 forecast_ids[i]['safety_stock_qty'] = forecast_ids[i]['safety_stock_qty'] + forecast_ids[i]['replenish_qty']
    #                                 forecast_ids[i]['replenish_qty'] = 0
    #                                 forecast_ids[i]['state'] = 'launched'

    #             elif(is_fabricate and product_template.bom_ids):
    #                 time_days = product_template.bom_ids[-1].x_studio_lead_time
    #                 quantity_week = math.ceil(time_days/7)
    #                 if(quantity_week > 0):
    #                     forecast_ids = production.get('forecast_ids')

                        
    #                     for i in range(len(forecast_ids)):
    #                         if(is_purchase):# and forecast_ids[i]['replenish_qty'] > 0):
    #                             forecast_ids[i]['replenish_qty'] = moq

    #                         if i < quantity_week:
    #                             forecast_ids[i]['safety_stock_qty'] = forecast_ids[i]['safety_stock_qty'] + forecast_ids[i]['replenish_qty']
    #                             forecast_ids[i]['replenish_qty'] = 0
    #                             forecast_ids[i]['state'] = 'launched'

    #     ###############################################

    #     company_groups = self.env.company.read([
    #         'mrp_mps_show_starting_inventory',
    #         'mrp_mps_show_demand_forecast',
    #         'mrp_mps_show_indirect_demand',
    #         'mrp_mps_show_actual_demand',
    #         'mrp_mps_show_to_replenish',
    #         'mrp_mps_show_actual_replenishment',
    #         'mrp_mps_show_safety_stock',
    #         'mrp_mps_show_available_to_promise',
    #     ])
    #     return {
    #         'dates': self.env.company._date_range_to_str(),
    #         'production_schedule_ids': productions_schedules_states,
    #         'manufacturing_period': self.env.company.manufacturing_period,
    #         'company_id': self.env.company.id,
    #         'groups': company_groups,
    #     }